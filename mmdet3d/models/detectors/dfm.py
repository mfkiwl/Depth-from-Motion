# Copyright (c) OpenMMLab. All rights reserved.
import torch

from mmdet3d.core import bbox3d2result
from mmdet.models import DETECTORS, build_backbone, build_head, build_neck
from mmdet.models.detectors import BaseDetector


@DETECTORS.register_module()
class DfM(BaseDetector):
    """Monocular 3D Object Detection with Depth from Motion."""

    def __init__(self,
                 backbone,
                 neck,
                 backbone_stereo,
                 backbone_3d,
                 bbox_head_3d,
                 neck_2d=None,
                 bbox_head_2d=None,
                 depth_head=None,
                 train_cfg=None,
                 test_cfg=None,
                 pretrained=None,
                 init_cfg=None):
        super().__init__(init_cfg=init_cfg)
        self.backbone = build_backbone(backbone)
        self.neck = build_neck(neck)
        backbone_stereo.update(cat_img_feature=self.neck.cat_img_feature)
        backbone_stereo.update(in_sem_channels=self.neck.sem_channels[-1])
        self.backbone_stereo = build_backbone(backbone_stereo)
        assert self.neck.cat_img_feature == \
            self.backbone_stereo.cat_img_feature
        assert self.neck.sem_channels[
            -1] == self.backbone_stereo.in_sem_channels
        self.backbone_3d = build_backbone(backbone_3d)
        if neck_2d is not None:
            self.neck_2d = build_neck(neck_2d)
        if bbox_head_2d is not None:
            self.bbox_head_2d = build_head(bbox_head_2d)
        if depth_head is not None:
            self.depth_head = build_head(depth_head)
        self.train_cfg = train_cfg
        self.test_cfg = test_cfg
        bbox_head_3d.update(train_cfg=train_cfg)
        bbox_head_3d.update(test_cfg=test_cfg)
        self.bbox_head_3d = build_head(bbox_head_3d)

    @property
    def with_neck_2d(self):
        return hasattr(self, 'neck_2d') and self.neck_2d is not None

    @property
    def with_bbox_head_2d(self):
        return hasattr(self, 'bbox_head_2d') and self.bbox_head_2d is not None

    @property
    def with_depth_head(self):
        return hasattr(self, 'depth_head') and self.depth_head is not None

    def extract_feat(self, img, img_metas):
        """
        Args:
            img (torch.Tensor): [B, N, C_in, H, W]
            img_metas (list): each element corresponds to a group of images.
                len(img_metas) == B.

        Returns:
            torch.Tensor: bev feature with shape [B, C_out, N_y, N_x].
        """
        # split input img into current and previous ones
        batch_size, N, C_in, H, W = img.shape
        cur_imgs = img[:, 0]
        prev_imgs = img[:, 1]  # TODO: to support multiple prev imgs
        # 2D backbone for feature extraction
        cur_feats = self.backbone(cur_imgs)
        cur_feats = [cur_imgs] + list(cur_feats)
        prev_feats = self.backbone(prev_imgs)
        prev_feats = [prev_imgs] + list(prev_feats)
        # SPP module as the feature neck
        cur_stereo_feat, cur_sem_feat = self.neck(cur_feats)
        prev_stereo_feat, prev_sem_feat = self.neck(prev_feats)
        # derive cur2prevs
        cur_pose = torch.tensor(
            [img_meta['cam2global'] for img_meta in img_metas],
            device=img.device)[:, None, :, :]  # (B, 1, 4, 4)
        prev_poses = []
        for img_meta in img_metas:
            sweep_img_metas = img_meta['sweep_img_metas']
            prev_poses.append([
                sweep_img_meta['cam2global']
                for sweep_img_meta in sweep_img_metas
            ])
        prev_poses = torch.tensor(prev_poses, device=img.device)
        pad_prev_cam2global = torch.eye(4)[None, None].expand(
            batch_size, N - 1, 4, 4).to(img.device)
        pad_prev_cam2global[:, :, :prev_poses.shape[-2], :prev_poses.
                            shape[-1]] = prev_poses
        pad_cur_cam2global = torch.eye(4)[None,
                                          None].expand(batch_size, 1, 4,
                                                       4).to(img.device)
        pad_cur_cam2global[:, :, :cur_pose.shape[-2], :cur_pose.
                           shape[-1]] = cur_pose
        # (B, N-1, 4, 4) * (B, 1, 4, 4) -> (B, N-1, 4, 4)
        # torch.linalg.solve is faster and more numerically stable
        # than torch.matmul(torch.linalg.inv(A), B)
        # empirical results show that torch.linalg.solve can derive
        # almost the same result with np.linalg.inv
        # while torch.linalg.inv can not
        cur2prevs = torch.linalg.solve(pad_prev_cam2global, pad_cur_cam2global)
        for meta_idx, img_meta in enumerate(img_metas):
            img_meta['cur2prevs'] = cur2prevs[meta_idx]
        # stereo backbone for depth estimation
        # volume_feat: (batch_size, Cv, Nz, Ny, Nx)
        volume_feat = self.backbone_stereo(cur_stereo_feat, prev_stereo_feat,
                                           img_metas, cur_sem_feat)
        # height compression
        _, Cv, Nz, Ny, Nx = volume_feat.shape
        bev_feat = volume_feat.view(batch_size, Cv * Nz, Ny, Nx)
        bev_feat_prehg, bev_feat = self.backbone_3d(bev_feat)
        return bev_feat

    def forward_train(self, img, img_metas, gt_bboxes_3d, gt_labels_3d,
                      depth_maps, **kwargs):
        bev_feat = self.extract_feat(img, img_metas)
        outs = self.bbox_head_3d([bev_feat])
        losses = self.bbox_head_3d.loss(*outs, gt_bboxes_3d, gt_labels_3d,
                                        img_metas)
        # TODO: loss_dense_depth, loss_2d, loss_imitation
        return losses

    def forward_test(self, img, img_metas, **kwargs):
        """Forward of testing.

        Args:
            img (torch.Tensor): Input images of shape (N, C_in, H, W).
            img_metas (list): Image metas.
        Returns:
            list[dict]: Predicted 3d boxes.
        """
        # not supporting aug_test for now
        return self.simple_test(img, img_metas)

    def simple_test(self, img, img_metas):
        bev_feat = self.extract_feat(img, img_metas)
        # bbox_head takes a list of feature from different levels as input
        # so need [bev_feat]
        outs = self.bbox_head_3d([bev_feat])
        bbox_list = self.bbox_head_3d.get_bboxes(*outs, img_metas)
        bbox_results = [
            bbox3d2result(det_bboxes, det_scores, det_labels)
            for det_bboxes, det_scores, det_labels in bbox_list
        ]
        # add pseudo-lidar label to each pred_dict for post-processing
        for bbox_result in bbox_results:
            bbox_result['pseudo_lidar'] = True
        return bbox_results

    def aug_test(self, imgs, img_metas, **kwargs):
        """Test with augmentations.

        Args:
            imgs (list[torch.Tensor]): Input images of shape (N, C_in, H, W).
            img_metas (list): Image metas.

        Returns:
            list[dict]: Predicted 3d boxes.
        """
        raise NotImplementedError
