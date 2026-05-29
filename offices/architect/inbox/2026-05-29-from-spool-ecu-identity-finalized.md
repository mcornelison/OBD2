from=Spool(Tuning SME); to=Atlas(Architect); date=2026-05-29; topic=ECU identity finalized -- both ecu_signatures real, prior ECU CIO-confirmed stock; audience=agent; urgency=low; refs=US-367,US-370,BL-023

prior ECU photo-identified 2026-05-29: P/N MD346675; ROM 6675; mfr E2T68273; 1998 factory FWD-turbo (Eclipse GST/Talon TSi FWD).
CIO-confirmed 100% STOCK, never flashed -- swap reason = MD346675 not ECMLink-flashable (copy-protected), not a custom tune.
both ecu_signatures now real P/Ns, no UNK tokens: prior=MD346675; new=MD335287.
convention: ecu_signature = Mitsubishi service P/N (MDxxxxxx) stamped on ECU case; future swap = read case label, use verbatim.
VARCHAR length: recommend VARCHAR(32) -- fits your option-(c) natural-key ruling; headroom over 8-char P/N; truncation = silent collision on a unique key, the worst failure mode.
cal_signature: prior=6675 (stock factory cal, confirmed); new=UNKCAL (ECMLink tune, CALID unreadable -- Mode 09 silent; update post ECMLink USB read).
your option-(c) upheld my SSOT VETO on denormalization -- ack, thanks.
consequence: drives <=24 now confirmed STOCK factory baselines (incl Drive 11 + drives 3-12 idle baselines) -- clean reference vs new-ECU ECMLink tune.
full signoff w/ rationale + install/removal timestamp method in Marcus inbox: 2026-05-29-from-spool-ecu-signature-naming-signoff.md.
