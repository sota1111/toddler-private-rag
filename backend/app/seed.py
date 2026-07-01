from sqlalchemy.orm import Session
from datetime import date, timedelta
from . import models
from .identity import DEFAULT_OWNER_ID

def seed_data(db: Session):
    # Check if data already exists
    if db.query(models.NurseryInfo).first():
        return

    today = date.today()
    tomorrow = today + timedelta(days=1)
    next_week = today + timedelta(days=5)

    sample_data = [
        {
            "title": "4月の園だより",
            "info_type": "資料",
            "content": "新年度が始まりました。今月の目標は「新しい環境に慣れる」です。",
            "date": today,
            "status": "対応済",
            "priority": "普通",
            "tags": "園だより,4月"
        },
        {
            "title": "春の遠足のお知らせ",
            "info_type": "行事",
            "content": "5月10日に代々木公園へ遠足に行きます。お弁当の準備をお願いします。",
            "event_date": today + timedelta(days=14),
            "status": "未対応",
            "priority": "高",
            "tags": "行事,遠足"
        },
        {
            "title": "健康診断票の提出",
            "info_type": "提出物",
            "content": "来週の月曜日までに健康診断票を記入して提出してください。",
            "due_date": today + timedelta(days=4),
            "status": "未対応",
            "priority": "高",
            "tags": "提出,健康診断"
        },
        {
            "title": "明日の持ち物（水遊び）",
            "info_type": "持ち物",
            "content": "明日は水遊びを予定しています。タオルと着替えを多めに持たせてください。",
            "date": tomorrow,
            "items": "タオル,着替え,ビニール袋",
            "status": "未対応",
            "priority": "普通",
            "tags": "持ち物,水遊び"
        },
        {
            "title": "給食献立（4月第3週）",
            "info_type": "給食",
            "content": "今週は春の食材をふんだんに使ったメニューです。筍ごはん、鰆の西京焼きなど。",
            "date": today,
            "status": "対応済",
            "priority": "低",
            "tags": "給食,献立"
        },
        {
            "title": "不審者対応訓練",
            "info_type": "行事",
            "content": "明日、不審者対応訓練を実施します。保護者の方は14時以降にお迎えをお願いします。",
            "event_date": tomorrow,
            "status": "対応済",
            "priority": "高",
            "tags": "行事,訓練"
        },
        {
            "title": "夏季保育への変更",
            "info_type": "休園変更",
            "content": "8月13日から15日は希望保育のみとなります。登園される方は事前に申請してください。",
            "date": today + timedelta(days=30),
            "status": "未対応",
            "priority": "普通",
            "tags": "変更,夏季保育"
        },
        {
            "title": "掲示板：忘れ物のお知らせ",
            "info_type": "掲示",
            "content": "玄関に青い帽子の忘れ物がありました。心当たりのある方は職員まで。",
            "date": today,
            "status": "対応済",
            "priority": "低",
            "tags": "掲示,忘れ物"
        },
        {
            "title": "親子ふれあいデー",
            "info_type": "行事",
            "content": "来週の土曜日に親子ふれあいデーを開催します。動きやすい服装でお越しください。",
            "event_date": next_week,
            "status": "未対応",
            "priority": "普通",
            "tags": "行事,親子イベント"
        },
        {
            "title": "入園説明会資料",
            "info_type": "資料",
            "content": "来年度の入園説明会で使用する資料のデジタル版です。",
            "date": today - timedelta(days=5),
            "status": "対応済",
            "priority": "普通",
            "tags": "資料,入園"
        }
    ]

    for data in sample_data:
        # SOT-1431: 開発用シードは主ユーザー(既定 owner)のデータとして登録する。
        db_info = models.NurseryInfo(owner_id=DEFAULT_OWNER_ID, **data)
        db.add(db_info)
    
    db.commit()
