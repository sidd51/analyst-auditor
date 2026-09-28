"""Pydantic contracts shared by model calls and web tools."""

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class PingResponse(BaseModel):
    """Tiny Step 2 schema used to prove structured output works."""

    reply: Literal["pong"]
    explanation: str = Field(
        min_length=1,
        max_length=120,
        description="A short confirmation that structured output worked.",
    )


class SearchHit(BaseModel):
    """One normalized result, regardless of which provider returned it."""

    title: str
    url: str
    snippet: str
    provider: Literal["tavily", "ddgs"]
    query: str

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        """Reject empty or non-web links before they reach the fetcher."""
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("search result URL must use http or https")
        return url


class SearchResponse(BaseModel):
    """Results plus enough status information to explain provider failures."""

    query: str
    hits: list[SearchHit] = Field(default_factory=list)
    providers_attempted: list[Literal["tavily", "ddgs"]] = Field(
        default_factory=list
    )
    errors: list[str] = Field(default_factory=list)
    fallback_used: bool = False


class FetchedPage(BaseModel):
    """Readable content and metadata extracted from one URL."""

    url: str
    final_url: str
    ok: bool
    kind: Literal["html", "pdf", "unknown"]
    extractor: Literal["trafilatura", "beautifulsoup", "pypdf", "none"]
    title: str = ""
    published_date: str | None = None
    text: str = ""
    page_count: int | None = None
    status_code: int | None = None
    error: str = ""


class FetchResponse(BaseModel):
    """A bounded group of pages returned in the original URL order."""

    requested_count: int
    selected_count: int
    skipped_count: int
    pages: list[FetchedPage] = Field(default_factory=list)


class EvidencePassage(BaseModel):
    """One source passage selected as possible evidence for a question."""

    passage_id: str
    url: str
    title: str
    document_kind: Literal["html", "pdf"]
    chunk_index: int
    pdf_page: int | None = None
    text: str
    matched_terms: list[str] = Field(default_factory=list)
    relevance_score: float
    estimated_tokens: int


class RetrievalResponse(BaseModel):
    """The bounded evidence packet that a future Analyst will receive."""

    question: str
    requirements: list[str] = Field(default_factory=list)
    documents_considered: int
    passages_considered: int
    passages_selected: int
    passages_omitted: int
    estimated_tokens: int
    token_budget: int
    passages: list[EvidencePassage] = Field(default_factory=list)


class QuestionSpecification(BaseModel):
    """What the question actually asks. Extracted before any search."""

    entities: list[str] = Field(
        min_length=1,
        description="Named companies, people, products, or other subjects.",
    )
    question_type: Literal[
        "identity",
        "multi_field",
        "comparison",
        "ranking",
        "exhaustive",
        "other",
    ] = Field(
        description=(
            "High-level question shape. Used later for planning, never to "
            "pick a page count."
        )
    )
    required_fields: list[str] = Field(
        min_length=1,
        description="Answer fields that must be filled or marked not_found.",
    )
    time_period: str | None = Field(
        default=None,
        description="Year, date, or range such as 2026 or last two years.",
    )
    geography: str | None = Field(
        default=None,
        description="Country or region if the question names one.",
    )
    required_count: int | None = Field(
        default=None,
        ge=1,
        description="How many results are requested, if the question says.",
    )
    ranking: bool = Field(
        default=False,
        description="True if the question asks for a top-N or most/least order.",
    )
    comparison: bool = Field(
        default=False,
        description="True if two or more entities must be compared.",
    )
    exhaustive: bool = Field(
        default=False,
        description="True only if the question asks to list every match.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Extra limits such as primary sources or as-of dates.",
    )
    not_found_rule: str = Field(
        min_length=1,
        description="When a required field must be reported as not_found.",
    )


class PagePolicy(BaseModel):
    """Python-owned fetch limits. The LLM cannot change these values."""

    initial_pages: int
    wave_size: int
    page_ceiling: int
    stop_when: Literal["requirements_covered"] = "requirements_covered"


class SpecifiedQuestion(BaseModel):
    """Question spec plus the fetch policy attached by Python."""

    question: str
    notes: list[str] = Field(default_factory=list)
    specification: QuestionSpecification
    page_policy: PagePolicy
    as_of_date: str
    resolved_time_period: str | None = None


class PlannedQuery(BaseModel):
    """One search query aimed at one or more required fields."""

    query: str = Field(min_length=1, description="The exact web search string.")
    targets: list[str] = Field(
        min_length=1,
        description="Required fields this query is trying to cover.",
    )
    reason: str = Field(
        min_length=1,
        description="Why this query is needed, in one short sentence.",
    )


class PlannerOutput(BaseModel):
    """Raw planner response before Python applies the query cap."""

    queries: list[PlannedQuery] = Field(min_length=1)


class ResearchPlan(BaseModel):
    """Bounded search plan that later steps will execute sequentially."""

    specified: SpecifiedQuestion
    queries: list[PlannedQuery]
    known_facts: list[str] = Field(default_factory=list)
    disputed_notes: list[str] = Field(default_factory=list)
    rejected_notes: list[str] = Field(default_factory=list)
    skipped_queries: list[PlannedQuery] = Field(default_factory=list)
    truncated: bool = False


class CandidateUrl(BaseModel):
    """One unique URL discovered by one or more planned searches."""

    url: str
    title: str = ""
    snippet: str = ""
    discovered_by: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)


class EvidencePacket(BaseModel):
    """First-wave evidence ready for a later Analyst call."""

    plan: ResearchPlan
    searches: list[SearchResponse] = Field(default_factory=list)
    candidates: list[CandidateUrl] = Field(default_factory=list)
    fetched: FetchResponse
    retrieval: RetrievalResponse
    pages_used: int
    next_wave_size: int
    unused_urls: list[str] = Field(default_factory=list)
    memory_verify: bool = False


class DraftClaim(BaseModel):
    """Model draft of one fact. Python keeps it only if the quote checks out."""

    field: str = Field(min_length=1, description="Required field this fact fills.")
    text: str = Field(min_length=1, description="One atomic factual statement.")
    quote: str = Field(min_length=1, description="Exact words copied from a passage.")
    passage_ids: list[str] = Field(min_length=1)
    period: str | None = Field(
        default=None,
        description="Date or window stated in the passage, if any.",
    )


class DraftUnanswered(BaseModel):
    """A required field or rank slot that the passages do not support."""

    field: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AnalystDraft(BaseModel):
    """Raw Analyst output before Python drops unsupported drafts."""

    claims: list[DraftClaim] = Field(default_factory=list)
    unanswered: list[DraftUnanswered] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list,
        description="Optional context such as planned expansions. Not facts.",
    )


class AnalystClaim(BaseModel):
    """A supported fact with a quote that appears in a cited passage."""

    claim_id: str
    field: str
    text: str
    quote: str
    passage_ids: list[str]
    urls: list[str]
    period: str | None = None


class UnansweredField(BaseModel):
    """Coverage record for something the passages could not support."""

    field: str
    reason: str


class AnalystResult(BaseModel):
    """Supported claims only, plus explicit unanswered fields."""

    claims: list[AnalystClaim] = Field(default_factory=list)
    unanswered: list[UnansweredField] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    dropped_drafts: int = 0


class CrossCheckVerdict(BaseModel):
    """Label for a claim that had only one source domain."""

    claim_id: str
    status: Literal[
        "corroborated",
        "single_source",
        "conflicting",
        "skipped_multi_source",
    ]
    independent_url: str | None = None
    reason: str = ""
    evidence_origin: Literal["reused_wave1", "new_search", "none"] = "none"


class CrossCheckItemDraft(BaseModel):
    """One support judgment in the batched cross-check call."""

    claim_id: str
    support: Literal["yes", "no", "conflict"]
    reason: str = Field(min_length=1)
    conflict_quote: str = ""


class CrossCheckDraft(BaseModel):
    """Raw batched entailment result before Python maps the labels."""

    items: list[CrossCheckItemDraft] = Field(default_factory=list)


class CrossCheckReport(BaseModel):
    """One verdict per Analyst claim after search/fetch plus one LLM batch."""

    verdicts: list[CrossCheckVerdict] = Field(default_factory=list)


class AuditItemDraft(BaseModel):
    """One (claim, cited source) judgment from the batched Auditor call."""

    claim_id: str
    source_id: str
    support: Literal["support", "silent", "conflict"]
    reason: str = Field(min_length=1)


class AuditDraft(BaseModel):
    """Raw batched entailment result before Python rolls up claim verdicts."""

    items: list[AuditItemDraft] = Field(default_factory=list)


class AuditSourceNote(BaseModel):
    """What one independently refetched citation said about one claim."""

    claim_id: str
    source_id: str
    url: str
    support: Literal["support", "silent", "conflict"]
    reason: str
    passage_ids: list[str] = Field(default_factory=list)
    available: bool = True


class ClaimAudit(BaseModel):
    """Final Auditor label for one Analyst claim."""

    claim_id: str
    verdict: Literal["SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "UNCITED"]
    reason: str
    source_notes: list[AuditSourceNote] = Field(default_factory=list)


class AuditReport(BaseModel):
    """One verdict per Analyst claim after independent refetch and judgment."""

    verdicts: list[ClaimAudit] = Field(default_factory=list)
    urls_refetched: list[str] = Field(default_factory=list)
    urls_skipped: list[str] = Field(default_factory=list)


class AnswerLine(BaseModel):
    """One verified claim the user is allowed to see."""

    field: str
    text: str
    claim_id: str
    urls: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class MissingLine(BaseModel):
    """A required field or rank slot with no verified claim."""

    field: str
    reason: str


class DisputedLine(BaseModel):
    """A claim the Auditor or cross-check marked as conflicting."""

    field: str
    claim_id: str
    reason: str
    urls: list[str] = Field(default_factory=list)


class FinalAnswer(BaseModel):
    """Deterministic user-facing answer. No extra model call."""

    complete: bool
    accepted: list[AnswerLine] = Field(default_factory=list)
    missing: list[MissingLine] = Field(default_factory=list)
    disputed: list[DisputedLine] = Field(default_factory=list)


class MemoryFact(BaseModel):
    """One accepted fact scoped to an entity. Never a whole previous answer."""

    entity: str
    field: str
    text: str
    quote: str = ""
    urls: list[str] = Field(default_factory=list)
    period: str | None = None
    as_of_date: str
    corroboration: Literal["corroborated", "single_source", "multi_source"] = (
        "single_source"
    )


class MemoryReject(BaseModel):
    """A disputed or rejected sentence the next planner must not reuse as fact."""

    entity: str
    field: str
    text: str
    status: Literal["rejected", "disputed"]
    reason: str
    urls: list[str] = Field(default_factory=list)
    as_of_date: str


class MemorySnapshot(BaseModel):
    """On-disk entity memory. Rebuilt per eval; not an answer cache."""

    facts: list[MemoryFact] = Field(default_factory=list)
    rejects: list[MemoryReject] = Field(default_factory=list)


class MemoryRecall(BaseModel):
    """Prompt lines for the planner. Facts and warnings stay separate."""

    facts: list[MemoryFact] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    known_fields: list[str] = Field(default_factory=list)
    disputed_notes: list[str] = Field(default_factory=list)
    disputed_fields: list[str] = Field(default_factory=list)
    rejected_notes: list[str] = Field(default_factory=list)
