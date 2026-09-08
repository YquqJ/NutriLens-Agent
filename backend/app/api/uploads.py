"""图片上传路由：multipart → OSS → 返回公网 URL。"""

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.db.models import User
from app.services.oss import upload_image

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class UploadResponse(BaseModel):
    image_url: str


@router.post("", response_model=UploadResponse)
async def upload(file: UploadFile, user: User = Depends(get_current_user)):
    """
    上传食物图片。返回的 URL 有两个用途：
    1. 存入 messages.image_url，前端展示；
    2. 作为 qwen-vl-max 的输入（DashScope 服务端拉取识别）。
    """
    url = await upload_image(file)
    return UploadResponse(image_url=url)
