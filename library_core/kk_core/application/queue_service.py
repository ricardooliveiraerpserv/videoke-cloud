"""Casos de uso da fila de cantores (separada de playlist).

Regras: entrar no fim; reordenar; avançar (marca o atual como concluído e
promove o próximo, emitindo NowSinging para o Segundo Monitor).
"""
from __future__ import annotations

import secrets

from kk_shared.contracts.dtos import EnqueueDTO, QueueItemView, SongRequestView
from kk_shared.contracts.enums import QueueStatus, RequestStatus
from kk_shared.events.session import (
    NowSinging,
    QueueItemAdded,
    QueueItemDone,
    QueueReordered,
    RequestApproved,
    RequestRejected,
    SongRequested,
)


class QueueService:
    def open_or_get_session(self, uow, name: str = "Sessão") -> str:
        return uow.queue.active_session() or uow.queue.create_session(name)

    def enqueue(self, uow, session_id: str, dto: EnqueueDTO) -> QueueItemView:
        song = uow.songs.get(dto.song_id)
        if not song or not song.media_files:
            raise ValueError("música sem versão tocável")
        best = song.best_version() or song.media_files[0]
        preset = uow.presets.get(dto.song_id, None)
        pitch = dto.pitch if dto.pitch is not None else (preset[0] if preset else 0)
        tempo = dto.tempo if dto.tempo is not None else (preset[1] if preset else 100)

        view = uow.queue.add(
            session_id=session_id, song_id=song.id, media_file_id=best.id,
            song_title=song.title, artists_text=", ".join(a.name for a in song.artists),
            singer=dto.singer, pitch=pitch, tempo=tempo, note=dto.note,
            status=QueueStatus.WAITING.value, position=uow.queue.next_position(session_id),
            estimated_duration_s=best.duration.seconds,
        )
        uow.add_event(QueueItemAdded(
            session_id=session_id, item_id=view.id, singer=dto.singer, song_title=song.title
        ))
        return view

    def list(self, uow, session_id: str) -> list[QueueItemView]:
        return uow.queue.list_active(session_id)

    # ------------------------------------------------------------------ Fase D
    # Convidado: código de sessão, pedido, e o operador aceita/recusa.
    def ensure_code(self, uow, session_id: str) -> str:
        """Devolve o código numérico da sessão, atribuindo um único se faltar."""
        sess = uow.queue.get_session(session_id)
        if sess is None:
            raise ValueError("sessão inexistente")
        if sess.code:
            return sess.code
        for _ in range(50):
            code = f"{secrets.randbelow(900000) + 100000}"   # 6 dígitos, 100000–999999
            if uow.queue.session_by_code(code) is None:
                uow.queue.set_code(session_id, code)
                return code
        raise RuntimeError("não foi possível gerar um código de sessão único")

    def session_by_code(self, uow, code: str) -> str | None:
        return uow.queue.session_by_code((code or "").strip())

    def request_song(self, uow, session_id: str, song_id: str, singer: str,
                    note: str = "", device: str = "") -> SongRequestView:
        """Convidado PEDE (não entra direto na fila): fica pendente de aprovação."""
        song = uow.songs.get(song_id)
        if not song or not song.media_files:
            raise ValueError("música sem versão tocável")
        view = uow.requests.create(
            session_id=session_id, song_id=song.id, song_title=song.title,
            artists_text=", ".join(a.name for a in song.artists),
            singer=(singer or "Convidado").strip(), note=note, device=device,
            status=RequestStatus.PENDING.value,
        )
        uow.add_event(SongRequested(
            session_id=session_id, request_id=view.id,
            singer=view.singer, song_title=song.title,
        ))
        return view

    def list_requests(self, uow, session_id: str,
                     status: str | None = "pending") -> list[SongRequestView]:
        return uow.requests.list_by_session(session_id, status or None)

    def approve_request(self, uow, request_id: str) -> QueueItemView:
        """Operador ACEITA → o pedido vira item de fila (dispara QueueItemAdded)."""
        m = uow.requests.get(request_id)
        if m is None:
            raise ValueError("pedido inexistente")
        if m.status != RequestStatus.PENDING.value:
            raise ValueError("pedido já resolvido")
        view = self.enqueue(
            uow, m.session_id,
            EnqueueDTO(song_id=m.song_id, singer=m.singer, note=m.note),
        )
        m.status = RequestStatus.APPROVED.value
        m.queue_item_id = view.id
        uow.add_event(RequestApproved(
            session_id=m.session_id, request_id=request_id, item_id=view.id,
        ))
        return view

    def reject_request(self, uow, request_id: str) -> None:
        """Operador RECUSA → o pedido é marcado e nunca entra na fila."""
        m = uow.requests.get(request_id)
        if m is None:
            raise ValueError("pedido inexistente")
        if m.status != RequestStatus.PENDING.value:
            return
        m.status = RequestStatus.REJECTED.value
        uow.add_event(RequestRejected(session_id=m.session_id, request_id=request_id))

    def reorder(self, uow, session_id: str, item_id: str, new_index: int) -> None:
        items = uow.queue.active_models(session_id)
        ids = [m.id for m in items]
        if item_id not in ids:
            return
        ids.remove(item_id)
        new_index = max(0, min(new_index, len(ids)))
        ids.insert(new_index, item_id)
        by_id = {m.id: m for m in items}
        for pos, iid in enumerate(ids):
            by_id[iid].position = pos
        uow.add_event(QueueReordered(session_id=session_id))

    def set_status(self, uow, item_id: str, status: QueueStatus) -> None:
        m = uow.queue.get(item_id)
        if m:
            m.status = status.value

    def remove(self, uow, item_id: str) -> None:
        m = uow.queue.get(item_id)
        if m:
            m.status = QueueStatus.SKIPPED.value

    def advance(self, uow, session_id: str) -> QueueItemView | None:
        current = uow.queue.current(session_id)
        if current:
            cm = uow.queue.get(current.id)
            cm.status = QueueStatus.DONE.value
            # registra no histórico automaticamente (a apresentação aconteceu)
            uow.history.record(
                song_id=cm.song_id, media_file_id=cm.media_file_id, session_id=session_id,
                singer=cm.singer, song_title=cm.song_title, artists_text=cm.artists_text,
            )
            uow.add_event(QueueItemDone(session_id=session_id, item_id=current.id))

        waiting = [m for m in uow.queue.active_models(session_id)
                   if m.status == QueueStatus.WAITING.value]
        if not waiting:
            return None
        nxt = waiting[0]
        nxt.status = QueueStatus.SINGING.value
        next_singer = waiting[1].singer if len(waiting) > 1 else ""
        uow.add_event(NowSinging(
            session_id=session_id, item_id=nxt.id, singer=nxt.singer,
            song_title=nxt.song_title, next_singer=next_singer,
        ))
        from ..infrastructure.repositories.queue_repositories import _to_view
        return _to_view(nxt)
