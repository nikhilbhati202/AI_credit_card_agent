"""Seed script: ingest the 4-5 real, manually-curated MVP cards (Section 6.6).

Run after `alembic upgrade head` against a fresh DB:
    .venv/Scripts/python -m database.seed

For each card this:
  1. Inserts a card_documents row (source metadata, hand-verified per Section 7.2).
  2. Runs the real ingestion pipeline (extract -> chunk -> embed) and stores document_chunks.
  3. Inserts hand-curated reward_rules rows (Section 11.1: fully manual extraction is the
     right choice at this scale), best-effort linked to the chunk that states the rule.

Every reward_rate/cap value below was read directly from the cited source_url and cross-
checked against the extracted chunk text - none of it is invented (see Section 1.2's core
constraint on this project).
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from database.db import SessionLocal
from database.models import (
    CapBasis,
    CapType,
    CardDocument,
    DocumentChunk,
    RewardRule,
    RewardRuleStatus,
    RewardUnit,
    TransferPartner,
    UserProfile,
)
from rag.chunk_documents import ChunkMetadata, chunk_metadata_json, chunk_pages
from rag.embed_documents import EMBEDDING_MODEL_VERSION, embed_passages
from rag.ingest_pdfs import extract_pdf_pages

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuleSpec:
    spend_category: str
    reward_rate: float
    reward_unit: RewardUnit
    cap_type: CapType | None = None
    cap_basis: CapBasis | None = None
    cap_value: float | None = None
    excess_reward_rate: float | None = None
    exclusion_flag: bool = False
    milestone_flag: bool = False
    confidence_score: float = 1.0
    exclusion_note: str | None = None
    citation_keyword: str | None = None  # best-effort text to locate the source chunk


@dataclass(frozen=True)
class CardSpec:
    card_name: str
    issuer: str
    document_type: str
    effective_date: date
    source_url: str
    pdf_path: str
    rules: list[RuleSpec] = field(default_factory=list)
    # (first_page, last_page), 1-indexed inclusive. SBI's T&C booklets are shared MITC
    # documents covering the whole card product (fraud protection, contactless limits,
    # mobile wallets, etc.), not just rewards - manually spot-checking retrieval (Section
    # 8.7) showed that generic boilerplate from these large documents was outranking the
    # actually relevant reward-rule chunks from smaller, single-purpose card documents once
    # queried alongside them. Restricting ingestion to the reward-program section is a
    # deliberate, hand-verified scoping decision, not a shortcut - every ingested page is
    # still ingested in full, just scoped to the content this system's use case is about.
    page_range: tuple[int, int] | None = None


CARDS: list[CardSpec] = [
    CardSpec(
        card_name="Axis Atlas",
        issuer="Axis Bank",
        document_type="Feature Terms & Conditions",
        effective_date=date(2024, 4, 20),
        source_url=(
            "https://www.axisbank.com/docs/default-source/default-document-library/"
            "credit-cards/terms-and-conditions-of-features-of-axis-bank-atlas-credit-card.pdf"
        ),
        pdf_path="data/raw_pdfs/axis-bank/atlas/2024-04-20.pdf",
        rules=[
            RuleSpec(
                spend_category="flights",
                reward_rate=5,
                reward_unit=RewardUnit.MILES,
                cap_type=CapType.MONTHLY,
                cap_basis=CapBasis.SPEND,
                cap_value=200_000,
                excess_reward_rate=2,
                citation_keyword="Earn 5 EDGE Miles for every Rs. 100 spent on Travel EDGE",
            ),
            RuleSpec(
                spend_category="hotels",
                reward_rate=5,
                reward_unit=RewardUnit.MILES,
                cap_type=CapType.MONTHLY,
                cap_basis=CapBasis.SPEND,
                cap_value=200_000,
                excess_reward_rate=2,
                citation_keyword="Direct hotel spends refer to purchases made at hotel owned",
            ),
            RuleSpec(
                spend_category="travel_agents",
                reward_rate=2,
                reward_unit=RewardUnit.MILES,
                exclusion_note="Bookings via travel agents/OTAs earn the base rate, not the "
                "5x direct-airline/hotel rate.",
                citation_keyword="corporate travel agents, online travel agencies",
            ),
            RuleSpec(
                spend_category="other",
                reward_rate=2,
                reward_unit=RewardUnit.MILES,
                exclusion_note="Excludes gold/jewellery, rent, wallet, government institutions, "
                "insurance, fuel, utilities and telecom spends (w.e.f. 20 Apr 2024).",
                citation_keyword="2 EDGE Miles per INR 100 spent",
            ),
            RuleSpec(
                spend_category="fuel",
                reward_rate=0,
                reward_unit=RewardUnit.MILES,
                exclusion_flag=True,
                exclusion_note="Fuel spends do not earn EDGE Miles.",
                citation_keyword="Utilities and Telecom",
            ),
        ],
    ),
    CardSpec(
        card_name="Axis ACE",
        issuer="Axis Bank",
        document_type="Cashback Proposition Terms & Conditions",
        effective_date=date(2024, 4, 20),
        source_url=(
            "https://www.axis.bank.in/docs/default-source/default-document-library/"
            "credit-card/axis-bank-ace-credit-card-tncs.pdf"
        ),
        pdf_path="data/raw_pdfs/axis-bank/ace/2024-04-20.pdf",
        rules=[
            RuleSpec(
                spend_category="utility_bills",
                reward_rate=5,
                reward_unit=RewardUnit.CASHBACK,
                cap_type=CapType.MONTHLY,
                cap_basis=CapBasis.REWARD_UNITS,
                cap_value=500,
                exclusion_note="Only via Google Pay; Rs.500/statement cap combined with the "
                "food delivery/cab category.",
                citation_keyword="Cashback on bill payments",
            ),
            RuleSpec(
                spend_category="food_delivery_cabs",
                reward_rate=4,
                reward_unit=RewardUnit.CASHBACK,
                cap_type=CapType.MONTHLY,
                cap_basis=CapBasis.REWARD_UNITS,
                cap_value=500,
                exclusion_note="Swiggy/Zomato/Ola only; Rs.500/statement cap combined with the "
                "utility-bills category.",
                citation_keyword="Swiggy, Zomato and Ola",
            ),
            RuleSpec(
                spend_category="other",
                reward_rate=1.5,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_note="Excludes non-Google-Pay utility bills, fuel, EMI, wallet loads, "
                "cash advances, rent, gold/jewelry, insurance, education, government services.",
                citation_keyword="Other eligible merchants",
            ),
            RuleSpec(
                spend_category="fuel",
                reward_rate=0,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_flag=True,
                exclusion_note="Fuel spends are excluded from cashback.",
                citation_keyword="fuel spends, EMI transactions",
            ),
        ],
    ),
    CardSpec(
        card_name="SBI Cashback",
        issuer="SBI Card",
        document_type="Terms & Conditions",
        # No explicit "last updated" date is printed in this booklet (unlike the Axis/ICICI
        # documents) - the fetch date is used, and this gap is called out in the Phase 1
        # report as a known limitation (Section 7.2 normally requires a visible source date).
        effective_date=date(2026, 7, 1),
        source_url="https://www.sbicard.com/sbi-card-en/assets/docs/pdf/ekit-tncs/cashback-tnc-ekit.pdf",
        pdf_path="data/raw_pdfs/sbi-card/cashback/2026-07-01.pdf",
        page_range=(32, 39),  # Section "11. CARD CASHBACK" through just before Section 12
        rules=[
            RuleSpec(
                spend_category="online_shopping",
                reward_rate=5,
                reward_unit=RewardUnit.CASHBACK,
                cap_type=CapType.MONTHLY,
                cap_basis=CapBasis.REWARD_UNITS,
                cap_value=2000,
                citation_keyword="Online Spends will be identified basis the online indicators",
            ),
            RuleSpec(
                spend_category="offline_retail",
                reward_rate=1,
                reward_unit=RewardUnit.CASHBACK,
                cap_type=CapType.MONTHLY,
                cap_basis=CapBasis.REWARD_UNITS,
                cap_value=2000,
                citation_keyword="Any transaction not categorized as online would be termed",
            ),
            RuleSpec(
                spend_category="fuel",
                reward_rate=0,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_flag=True,
                exclusion_note="Fuel spends are excluded from Card Cashback.",
                citation_keyword="Any purchases at petrol pumps",
            ),
            RuleSpec(
                spend_category="rent",
                reward_rate=0,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_flag=True,
                exclusion_note="Rent/property management payments do not earn Card Cashback.",
                citation_keyword="Payments towards Rent",
            ),
            RuleSpec(
                spend_category="utility_bills",
                reward_rate=0,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_flag=True,
                exclusion_note="Utility bill payments do not earn Card Cashback.",
                citation_keyword="Utility transactions identified under MCCs",
            ),
            RuleSpec(
                spend_category="insurance",
                reward_rate=0,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_flag=True,
                exclusion_note="Insurance premium payments do not earn Card Cashback.",
                citation_keyword="Insurance transactions identified under MCCs",
            ),
        ],
    ),
    CardSpec(
        card_name="SBI SimplyCLICK",
        issuer="SBI Card",
        document_type="Terms & Conditions",
        effective_date=date(2026, 7, 1),  # same no-printed-date limitation as SBI Cashback
        source_url="https://www.sbicard.com/sbi-card-en/assets/docs/pdf/SimplyClick-TnC.pdf",
        pdf_path="data/raw_pdfs/sbi-card/simplyclick/2026-07-01.pdf",
        page_range=(14, 49),  # Exclusive Features + Reward Point Program sections
        rules=[
            RuleSpec(
                spend_category="partner_brand_online",
                reward_rate=10,
                reward_unit=RewardUnit.POINTS,
                confidence_score=0.9,
                exclusion_note="10x applies only to SimplyCLICK's listed exclusive online "
                "partner brands (subject to the partner providing eligible transaction IDs).",
                citation_keyword="10X Reward Points are applicable only when payment is done",
            ),
            RuleSpec(
                spend_category="online_shopping",
                reward_rate=5,
                reward_unit=RewardUnit.POINTS,
                cap_type=CapType.MONTHLY,
                cap_basis=CapBasis.REWARD_UNITS,
                cap_value=10_000,
                excess_reward_rate=1,
                exclusion_note="5x on other online spends, capped at 10,000 points/month; "
                "1 point/Rs.100 beyond that.",
                citation_keyword="5X Reward Points are applicable for all online spends",
            ),
            RuleSpec(
                spend_category="other",
                reward_rate=1,
                reward_unit=RewardUnit.POINTS,
                citation_keyword="every Rs.100 spent will accrue 1 Reward Point",
            ),
            RuleSpec(
                spend_category="fuel",
                reward_rate=0,
                reward_unit=RewardUnit.POINTS,
                exclusion_flag=True,
                exclusion_note="Offline fuel transactions do not earn Reward Points.",
                citation_keyword="Offline Fuel transaction",
            ),
        ],
    ),
    CardSpec(
        card_name="ICICI Amazon Pay",
        issuer="ICICI Bank",
        document_type="Terms & Conditions",
        effective_date=date(2026, 1, 13),
        source_url="https://www.icici.bank.in/managed-assets/docs/personal/cards/tc-for-amazon-pay-credit-card.pdf",
        pdf_path="data/raw_pdfs/icici-bank/amazon-pay/2026-01-13.pdf",
        rules=[
            RuleSpec(
                spend_category="amazon_prime",
                reward_rate=5,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_note="Requires active Amazon Prime membership; excludes Gold Coins "
                "and flight/hotel bookings on Amazon.",
                citation_keyword="For Card Members having Prime Membership",
            ),
            RuleSpec(
                spend_category="amazon_non_prime",
                reward_rate=3,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_note="Excludes Gold Coins and flight/hotel bookings on Amazon.",
                citation_keyword="For Card Members not having Prime Membership",
            ),
            RuleSpec(
                spend_category="digital_categories",
                reward_rate=2,
                reward_unit=RewardUnit.CASHBACK,
                citation_keyword="digitally fulfilled categories",
            ),
            RuleSpec(
                spend_category="other",
                reward_rate=1,
                reward_unit=RewardUnit.CASHBACK,
                citation_keyword="1% Reward Points will be offered for all purchases other than",
            ),
            RuleSpec(
                spend_category="fuel",
                reward_rate=0,
                reward_unit=RewardUnit.CASHBACK,
                exclusion_flag=True,
                exclusion_note="Fuel spends are not eligible for Reward Points; a 1% fuel "
                "surcharge waiver applies separately.",
                citation_keyword="they will be charged a",
            ),
        ],
    ),
]


def _find_chunk_id(chunks: list[DocumentChunk], keyword: str | None) -> int | None:
    if not keyword:
        return None
    needle = keyword.lower()
    for chunk in chunks:
        if needle in chunk.chunk_text.lower():
            return chunk.id
    logger.warning("No chunk matched citation keyword %r", keyword)
    return None


def seed_card(db: Session, spec: CardSpec) -> None:
    logger.info("Ingesting %s (%s)", spec.card_name, spec.pdf_path)

    document = CardDocument(
        card_name=spec.card_name,
        issuer=spec.issuer,
        document_type=spec.document_type,
        effective_date=spec.effective_date,
        source_url=spec.source_url,
    )
    db.add(document)
    db.flush()  # assign document.id

    pages = extract_pdf_pages(spec.pdf_path)
    if spec.page_range:
        first, last = spec.page_range
        pages = [p for p in pages if first <= p.page_number <= last]
        logger.info("  -> scoped to pages %d-%d (%d pages)", first, last, len(pages))
    metadata = ChunkMetadata(
        card_name=spec.card_name,
        issuer=spec.issuer,
        document_type=spec.document_type,
        effective_date=spec.effective_date,
        source_url=spec.source_url,
    )
    chunks = chunk_pages(pages, metadata)
    if not chunks:
        raise ValueError(f"{spec.card_name}: chunking produced zero chunks")

    embeddings = embed_passages([c.text for c in chunks])

    db_chunks = [
        DocumentChunk(
            document_id=document.id,
            card_name=spec.card_name,
            chunk_text=chunk.text,
            page_number=chunk.page_number,
            embedding=embedding,
            metadata_json=chunk_metadata_json(metadata, EMBEDDING_MODEL_VERSION),
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    db.add_all(db_chunks)
    db.flush()  # assign ids so citation lookup below can reference them
    logger.info("  -> %d chunks embedded and stored", len(db_chunks))

    for rule in spec.rules:
        db.add(
            RewardRule(
                document_id=document.id,
                source_chunk_id=_find_chunk_id(db_chunks, rule.citation_keyword),
                card_name=spec.card_name,
                spend_category=rule.spend_category,
                reward_rate=rule.reward_rate,
                reward_unit=rule.reward_unit,
                cap_type=rule.cap_type,
                cap_basis=rule.cap_basis,
                cap_value=rule.cap_value,
                excess_reward_rate=rule.excess_reward_rate,
                exclusion_flag=rule.exclusion_flag,
                exclusion_note=rule.exclusion_note,
                milestone_flag=rule.milestone_flag,
                confidence_score=rule.confidence_score,
                status=RewardRuleStatus.ACTIVE,
            )
        )
    logger.info("  -> %d reward_rules inserted", len(spec.rules))


def seed_mock_data(db: Session) -> None:
    """A small synthetic card (Section 6.6: mock data) so unit/integration tests never
    depend on real card data changing.
    """
    document = CardDocument(
        card_name="Test Card Alpha",
        issuer="Test Bank",
        document_type="Terms & Conditions",
        effective_date=date(2025, 1, 1),
        source_url="https://example.com/test-card-alpha-tnc.pdf",
    )
    db.add(document)
    db.flush()

    db.add(
        RewardRule(
            document_id=document.id,
            card_name="Test Card Alpha",
            spend_category="groceries",
            reward_rate=10,
            reward_unit=RewardUnit.CASHBACK,
            cap_type=CapType.MONTHLY,
            cap_basis=CapBasis.REWARD_UNITS,
            cap_value=1000,
            confidence_score=1.0,
            status=RewardRuleStatus.ACTIVE,
        )
    )


def reset_database(db: Session) -> None:
    """Wipe all seedable tables for a clean re-seed (dev-only script, Section 6.6)."""
    db.execute(delete(RewardRule))
    db.execute(delete(TransferPartner))
    db.execute(delete(DocumentChunk))
    db.execute(delete(UserProfile))
    db.execute(delete(CardDocument))
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        reset_database(db)
        for spec in CARDS:
            seed_card(db, spec)
        seed_mock_data(db)
        db.commit()
        logger.info("Seed complete: %d real cards + 1 mock card", len(CARDS))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
