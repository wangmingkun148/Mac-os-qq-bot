"""Bridges the engine to the live status feed."""
from __future__ import annotations
import time


class LiveMixin:
    def live_engine(self):
        self.live.set_engine(state=self.status.get("state"), message=self.status.get("message"), paused=self.paused,
                             model=self.status.get("model", ""))

    def live_sync(self):
        """Main-thread only: mirror the not-yet-handled message batches into the live feed."""
        self.live.set_waiting({group: (self.conversation_details.get(group, {}).get("title", group), list(messages))
                               for group, messages in self.tracker.pending.items() if messages})
        wall = time.time() - time.monotonic()      # monotonic -> wall clock for the UI
        self.live.set_unvisited([
            {"group": g, "title": self.conversation_details.get(g, {}).get("title", g), "count": self.initial_new[g],
             "since": wall + since} for g, since in self.changed_since.items() if self.initial_new[g]])
        self.live.flush()

    def live_finish(self, outcome, text=""):
        turn, self.live_turn = self.live_turn, None
        self.live.finish(turn, outcome, text)

    def begin_flight(self, group, fresh, kind="reply", stage="judging", detail="", continue_turn=False):
        """Mark a model/image job as in flight and open (or continue) its live-feed turn."""
        self.inflight = (group, fresh)
        self.flight_epoch = self.epoch
        if continue_turn and self.live_turn:
            self.live.step(self.live_turn, stage, detail)
            return
        self.live_finish("cancelled", "被新的任务取代")
        title = self.conversation_details.get(group, {}).get("title", group)
        self.live_turn = self.live.begin(group, title, kind, fresh)
        self.live.step(self.live_turn, stage, detail)

    def on_progress(self, text, decision=None, thoughts=None):
        """Called from the model worker thread."""
        self.set_status(text, "thinking")
        self.live.step(self.live_turn, "generating", text)
        self.live.update(self.live_turn, **{k: v for k, v in (("decision", decision), ("thoughts", thoughts)) if v})
