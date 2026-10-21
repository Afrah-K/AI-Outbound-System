from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from datetime import datetime

from app.models.base import Base


class PlacementCheck(Base):
    """
    Where one email sent between your own connected inboxes landed in the
    recipient's mailbox (Primary inbox, a Gmail tab, Spam...). Warmup emails
    are checked automatically; placement tests send a campaign's real copy.
    """
    __tablename__ = "placement_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)  # the account this belongs to
    source = Column(String(20), index=True)  # warmup | test
    sender_inbox_id = Column(Integer, ForeignKey("inboxes.id", ondelete="SET NULL"), index=True)
    recipient_inbox_id = Column(Integer, ForeignKey("inboxes.id", ondelete="SET NULL"), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)  # for tests of a campaign's copy
    subject = Column(String(500))

    sender_message_id = Column(String(255))   # Gmail id in the sender's mailbox
    rfc822_message_id = Column(String(500))   # Message-ID header, used to find it in the recipient's

    # pending | inbox | promotions | updates | social | forums | spam | other | missing
    placement = Column(String(20), default="pending", index=True)
    sent_at = Column(DateTime, default=datetime.utcnow, index=True)
    checked_at = Column(DateTime)
    attempts = Column(Integer, default=0)
    error = Column(Text)
