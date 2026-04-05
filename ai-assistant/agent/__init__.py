#!/usr/bin/env python3
"""
Agent package initialisation.

Exposes the main classes for convenient imports:
    from agent import BidAgent, ComputerController, WebAccessController
"""

from agent.bid_agent import BidAgent
from agent.computer_control import ComputerController
from agent.web_access import WebAccessController

__all__ = ["BidAgent", "ComputerController", "WebAccessController"]
