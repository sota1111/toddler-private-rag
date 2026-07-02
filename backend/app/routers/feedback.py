"""SOT-1473: ユーザーからの回答フィードバック（👍/👎）収集エンドポイント。

RAG 回答に対するユーザーの評価を永続化し、精度改善の一次データにする。
owner ごとにスコープする（SOT-1431 と同方式）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..routers.auth import get_current_user

router = APIRouter(
    prefix="/feedback",
    tags=["feedback"],
)


@router.post("", response_model=schemas.AnswerFeedbackResponse)
def create_feedback(
    payload: schemas.AnswerFeedbackCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    feedback = models.AnswerFeedback(
        owner_id=current_user,
        question=payload.question,
        answer=payload.answer,
        rating=payload.rating,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


@router.get("/summary", response_model=schemas.AnswerFeedbackSummary)
def feedback_summary(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    q = db.query(models.AnswerFeedback).filter(
        models.AnswerFeedback.owner_id == current_user
    )
    up = q.filter(models.AnswerFeedback.rating == "up").count()
    down = q.filter(models.AnswerFeedback.rating == "down").count()
    return schemas.AnswerFeedbackSummary(up=up, down=down, total=up + down)
