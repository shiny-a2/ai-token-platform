"""FSM states for multi-step bot flows."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    choosing_language = State()
    privacy = State()
    chatting = State()          # free chat with active mode
    confirming_send = State()   # waiting yes/no on cost estimate
    image_prompt = State()      # waiting for image description
    research_prompt = State()   # waiting for research question
    awaiting_receipt = State()  # waiting for receipt photo / txid
    support_message = State()   # waiting for a support message
