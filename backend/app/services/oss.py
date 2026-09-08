"""
阿里云 OSS 上传 service。

上传链路（刻意选后端中转而非前端直传）：
    前端 multipart → FastAPI /api/uploads → 本模块 put 到 OSS → 返回公网 URL
理由：
1. 前端直传需要 STS 临时凭证或后端签名接口，复杂度高，中转的带宽开销
   对单图 ~2MB 的食物照片完全可接受；
2. 后端可以顺手做文件类型/大小校验，安全性更好；
3. 返回的 URL 直接传给 qwen-vl-max（DashScope 服务端拉取该 URL 识别），
   OSS 与 DashScope 同在阿里云内网环境，访问稳定。

注：bucket 需设置为公共读（或改用预签名 URL），
因为 DashScope 的识别服务需要能匿名访问该图片 URL。
"""

import uuid

import oss2
from fastapi import HTTPException, UploadFile

from app.core.config import settings

# 允许的图片类型（MIME 白名单，防止伪装成图片的可执行文件）
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


def _bucket() -> oss2.Bucket:
    """按需构建 OSS 客户端（懒加载，未配置时调用即报 500）。"""
    if not settings.oss_bucket_name:
        raise HTTPException(status_code=500, detail="OSS 未配置，请检查环境变量")
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket_name)


async def upload_image(file: UploadFile) -> str:
    """
    校验并上传图片到 OSS，返回公网 URL。

    对象命名：nutrilens/{uuid}.{ext}
    用 UUID 而非原文件名：避免中文/特殊字符转义问题与同名覆盖。
    """
    # 1. 类型校验
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPG / PNG / WebP 图片")

    # 2. 读取并校验大小（读进内存，5MB 上限下没有流式处理的必要）
    data = await file.read()
    if len(data) > _MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="图片大小不能超过 5MB")

    # 3. 生成对象名并上传
    ext = (file.filename or "img.jpg").rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"
    object_key = f"nutrilens/{uuid.uuid4().hex}.{ext}"

    try:
        _bucket().put_object(object_key, data)
    except oss2.exceptions.OssError as e:
        raise HTTPException(status_code=502, detail=f"OSS 上传失败: {e}") from e

    # 4. 拼公网 URL（bucket 公共读模式）
    return f"{settings.oss_public_base_url.rstrip('/')}/{object_key}"
