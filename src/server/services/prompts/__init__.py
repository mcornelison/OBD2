################################################################################
# File Name: __init__.py
# Purpose/Description: Prompts package marker. Template content lives in the
#                      adjacent .txt / .jinja / .md files, not in Python, so
#                      Spool can edit them without a code change (US-CMP-005).
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial package marker for US-CMP-005
# ================================================================================
################################################################################

"""Spool-authored prompt templates for the Ollama analysis pipeline.

Files loaded from this directory (paths resolved relative to ``__file__``):

* ``system_message.txt`` — invariant system role content. Loaded verbatim on
  every request.
* ``user_message.jinja`` — per-drive Jinja template. Rendered against analytics
  output before the call.
* ``DESIGN_NOTE.md`` — Spool's design rationale and quality gates. Reference
  only; not loaded at runtime.

Per Spool's handoff note: do NOT inline these templates into Python source.
The authoritative copies live here so Spool can iterate on prompt content
without a code change.
"""
