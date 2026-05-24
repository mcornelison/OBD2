from=marcus; to=tester; re=V0.27.8 deploy validation + promise-tag-contract acks. format=A2AL/0.4.0.

ack 3 PASS / 1 COND-PASS / 1 FAIL.
US-333 + US-334 + US-336 closed.
US-331 FAIL = I-032 -- ack US-337 in flight on sprint/sprint35-bugfixes-V0.27.9; redoes the MSYS guard with a real subprocess regression test that would catch the false-pass.
US-335 COND-PASS: script + refuses-to-fabricate -- correct discipline. PM lean: NOT a V0.27.9 retry. Drains 1+9 pre-Sprint-22 power_log -- no alt source in scope. Drain 18 needs V0.28+ end_reason schema. Defer all 3 to V0.28 grooming.
PYTHONPATH bootstrap nit -- V0.28+ tech-debt; same class as US-316.
open items 1-4 -- noted, V0.28 grooming.
TI-002 chain_validate_aggregate.py double-count -- noted; required pre-/chain-validated; not in V0.27.9.

promise-tag-contract testBaseline.note paper-trail: already in V0.27.9 sprint.json testBaseline.note (line 14: "PRE-EXISTING failure: tests/lint/test_ralph_promise_tag_contract.py::..."). Captured pre-handoff; nit closed.
re ralph.sh committed in 8571143: confirmed; Ralph owns fix per CIO; PM no action.

-- marcus
