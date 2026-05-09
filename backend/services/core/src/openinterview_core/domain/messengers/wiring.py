"""One-shot construction of the messenger kernel + plugin registry from
the FastAPI app state. Called from `create_app`.
"""
from __future__ import annotations

from pathlib import Path

from openinterview_logging import get_logger

from ..interviewer import InterviewerAgent, SessionEvaluator
from ..memory import MemoryRetriever
from ..mentor import MentorAgent
from ..projects.embedder import GatewayEmbedder
from ..qa import QAGenerationService
from .agent_facade_impl import CoreAgentFacade
from .plugins.whatsapp.pairing import WhatsAppPairingTracker
from .registry import PluginRegistry, build_registry
from .sdk.filter_store import MessengerFilterStore
from .sdk.kernel import MessengerKernel
from .sdk.pair_tokens import PairTokenStore
from .sdk.session_store import ActiveSessionStore, MessengerLinkStore

log = get_logger(__name__)


def build_messenger_runtime(app) -> tuple[MessengerKernel, PluginRegistry]:
    sm = app.state.db.sessionmaker
    gateway = app.state.gateway
    vector_store = app.state.vector_store
    blob = app.state.blob

    embedder = GatewayEmbedder(gateway)
    retriever = MemoryRetriever(
        sessionmaker=sm,
        gateway=gateway,
        embedder=embedder,
        vector_store=vector_store,
    )
    mentor = MentorAgent(
        gateway=gateway,
        retrieval_service=app.state.retrieval_service,
        blob=blob,
    )
    interviewer = InterviewerAgent(
        sessionmaker=sm,
        gateway=gateway,
        retrieval_service=app.state.retrieval_service,
    )
    evaluator = SessionEvaluator(
        sessionmaker=sm, gateway=gateway, retriever=retriever
    )
    qa = QAGenerationService(
        sessionmaker=sm,
        gateway=gateway,
        vector_store=vector_store,
        retrieval_service=app.state.retrieval_service,
    )

    facade = CoreAgentFacade(
        sessionmaker=sm,
        mentor=mentor,
        interviewer=interviewer,
        evaluator=evaluator,
        qa=qa,
    )
    kernel = MessengerKernel(
        agent=facade,
        links=MessengerLinkStore(sm),
        active=ActiveSessionStore(sm),
        pair_tokens=PairTokenStore(sm),
        filters=MessengerFilterStore(sm),
    )

    plugins_root = Path(__file__).parent / "plugins"
    registry = build_registry(plugins_root)

    # WhatsApp-specific: in-memory pair-id ↔ user map, used so the bridge's
    # "paired" webhook can be attributed to a particular app user.
    wa_tracker = WhatsAppPairingTracker()
    app.state.whatsapp_pairing_tracker = wa_tracker

    # Inject kernel handle + pairing hook into each plugin.
    for manifest, plugin in registry.all():
        try:
            plugin._handle_turn = lambda p, t, k=kernel: k.handle_turn(p, t)  # type: ignore[attr-defined]
        except Exception:
            pass
        if manifest.id == "whatsapp":
            plugin._pairing_hook = _WhatsAppPairingHook(  # type: ignore[attr-defined]
                tracker=wa_tracker,
                links=MessengerLinkStore(sm),
                plugin=plugin,
            )

    return kernel, registry


class _WhatsAppPairingHook:
    """Translates the bridge's "paired" webhook into a `MessengerLink` row
    for the user who started the pairing.
    """

    def __init__(self, *, tracker, links, plugin) -> None:
        self._tracker = tracker
        self._links = links
        self._plugin = plugin

    async def on_paired(
        self,
        *,
        pair_id: str,
        account_id: str,
        jid: str,
        phone_number: str,
        restored: bool = False,
    ) -> None:
        # The plugin already refreshed its in-memory account_for_jid map
        # by the time we're called. For a *restored* socket there's no
        # waiting user — the link row was minted on the original pair.
        if restored:
            log.info(
                "whatsapp_account_restored",
                account_id_tail=account_id[-6:],
                phone=phone_number,
            )
            return

        user_id = self._tracker.pop_user_for_account(account_id=account_id)
        if user_id is None and pair_id:
            user_id = self._tracker.get_user(pair_id=pair_id)
        if user_id is None:
            log.warning(
                "whatsapp_paired_unknown_pair", account_id_tail=account_id[-6:]
            )
            return
        await self._links.link(
            user_id=user_id,
            channel="whatsapp",
            external_id=jid,
            display_name=phone_number,
        )
