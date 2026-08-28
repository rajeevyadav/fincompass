/*
 * FinCompass presentation / translation layer.
 *
 * ONE place that turns backend values and machine-readable reason codes into
 * plain language for the Guided experience. Pure functions only: no DOM, no
 * network, no app state. The frontend maps codes to language HERE — it must not
 * scatter English through app.js or parse arbitrary backend error strings.
 *
 * Design rules:
 *   - Never emit Buy / Sell / Hold or any recommendation.
 *   - Never imply certainty, safety, accuracy, or profit.
 *   - Prefer the model's recorded neutral/abstention contract over invented bands.
 *   - When a reliable explanation is unavailable, say so — do not fabricate one.
 *
 * Exposed as the global `FCP` (no ES modules — app.js is a plain script).
 */
(function (global) {
  "use strict";

  function clampProb(p) {
    var v = Number(p);
    if (!isFinite(v)) return null;
    if (v < 0) v = 0;
    if (v > 1) v = 1;
    return v;
  }

  // Whole-percent string for prose, e.g. 0.6785 -> "68%". Deliberately coarse:
  // plain-language interpretation should not imply false precision.
  function pctWord(p) {
    var v = clampProb(p);
    return v === null ? "—" : Math.round(v * 100) + "%";
  }

  // User-friendly names for common benchmarks/indices. Raw tickers like ^GSPC
  // are never shown to a Guided user. Unknown symbols are cleaned (drop the ^).
  var BENCHMARK_NAMES = {
    "^GSPC": "S&P 500", "SPX": "S&P 500", "SPY": "S&P 500", "$SPX": "S&P 500",
    "^IXIC": "Nasdaq Composite", "^NDX": "Nasdaq-100", "QQQ": "Nasdaq-100",
    "^DJI": "Dow Jones Industrial Average", "DIA": "Dow Jones Industrial Average",
    "^RUT": "Russell 2000", "IWM": "Russell 2000",
    "^GSPTSE": "S&P/TSX Composite", "^FTSE": "FTSE 100", "^N225": "Nikkei 225",
    "^STOXX50E": "Euro Stoxx 50", "^VIX": "Volatility (VIX)",
  };

  function friendlyBenchmark(sym) {
    if (!sym) return "its benchmark";
    var key = String(sym).toUpperCase();
    if (BENCHMARK_NAMES[key]) return BENCHMARK_NAMES[key];
    return key.replace(/^[\^$]/, ""); // strip index prefix for unknowns
  }

  // Plain event category for the Live "What changed?" panel.
  function describeEventCategory(source, eventType) {
    var s = String(source || "").toLowerCase();
    var t = String(eventType || "").toLowerCase();
    if (t.indexOf("vol") >= 0 || s.indexOf("vix") >= 0) return "Volatility / market stress";
    if (s.indexOf("sec") >= 0 || t.indexOf("filing") >= 0 || t.indexOf("form") >= 0) return "Company filing";
    if (s.indexOf("macro") >= 0 || s.indexOf("fred") >= 0) return "Macro environment";
    if (s.indexOf("bench") >= 0) return "Benchmark movement";
    if (s.indexOf("market") >= 0 || s.indexOf("price") >= 0) return "Price / market movement";
    return "Market information";
  }

  function horizonWords(target) {
    target = target || {};
    if (target.horizon_months) {
      var m = Number(target.horizon_months);
      if (m === 12) return "12 months";
      if (m % 12 === 0) return (m / 12) + " years";
      return m + " months";
    }
    if (target.horizon_trading_days) {
      return Number(target.horizon_trading_days) + " trading days";
    }
    return "the selected period";
  }

  // Plain sentence defining the event the probability refers to.
  function describeEvent(target) {
    target = target || {};
    var bench = friendlyBenchmark(target.benchmark);
    var horizon = horizonWords(target);
    var thr = Number(target.excess_return_threshold || 0);
    var by = thr > 0 ? " by more than " + Math.round(thr * 100) + " percentage points" : "";
    return "the chance that this stock outperforms " + bench + " over " + horizon + by + ".";
  }

  /*
   * describeForecastProbability(probability, abstain, target)
   * Returns { percent, headline, band, interpretation, event, meaning, isNeutral }.
   * The interpretation is symmetric: a probability well below 50% is a signal
   * toward UNDER-performance, stated with the same humility as the upside.
   */
  function describeForecastProbability(probability, abstain, target) {
    var p = clampProb(probability);
    var percent = pctWord(p);
    var event = describeEvent(target);
    var bench = friendlyBenchmark(target && target.benchmark);
    var horizon = horizonWords(target);
    var meaning =
      "FinCompass is estimating " + event +
      " A " + percent + " forecast is a probability for that event — it is not a predicted return.";

    if (p === null) {
      return {
        percent: "—", headline: "No probability available", band: "unavailable",
        interpretation: "The model did not return a probability for this stock.",
        event: event, meaning: meaning, isNeutral: true,
      };
    }

    // Honour the model's own decision-neutral contract first.
    if (abstain) {
      return {
        percent: percent, headline: "Close to even",
        band: "neutral",
        interpretation:
          "This estimate sits within the model's decision-neutral zone, so it should not be read as a directional call.",
        event: event, meaning: meaning, isNeutral: true,
      };
    }

    var d = Math.abs(p - 0.5);
    var up = p >= 0.5;
    var side = up ? "outperformance" : "underperformance";
    var otherName = up ? bench : "this stock"; // for readability only
    var interpretation, band, headline;

    if (d < 0.05) {
      band = "neutral";
      headline = "Close to even";
      interpretation = "Close to even. The model does not show a strong direction.";
    } else if (d < 0.15) {
      band = up ? "lean-up" : "lean-down";
      headline = up ? "Leans toward outperformance" : "Leans toward underperformance";
      interpretation =
        "The model leans toward " + side + " over " + horizon +
        ", but uncertainty remains substantial.";
    } else {
      band = up ? "signal-up" : "signal-down";
      headline = up ? "Stronger signal for outperformance" : "Stronger signal for underperformance";
      interpretation =
        "The model shows a stronger historical signal for " + side +
        ". This is still uncertain and is not a guarantee.";
    }

    return {
      percent: percent, headline: headline, band: band,
      interpretation: interpretation, event: event, meaning: meaning,
      isNeutral: band === "neutral",
    };
  }

  /*
   * describeModelTier(validationTier) -> { label, level, blurb }
   * `level` drives badge styling; text never says "safe"/"proven"/"profitable".
   */
  function describeModelTier(validationTier) {
    switch (String(validationTier || "").toLowerCase()) {
      case "validated_market":
        return {
          label: "Market validated", level: "market",
          blurb:
            "Passed the stronger market-validation tier — point-in-time features, " +
            "survivorship control, delistings and corporate-action-adjusted prices are documented.",
        };
      case "validated_research":
        return {
          label: "Research validated", level: "research",
          blurb:
            "This model passed the configured historical research tests. It has not earned " +
            "the stronger market-validation tier, so treat its forecast as research evidence " +
            "rather than a trading signal.",
        };
      case "rejected":
        return {
          label: "Not eligible", level: "blocked",
          blurb: "This candidate did not meet the validation requirements and cannot be used for forecasts.",
        };
      case "fixture_only":
        return {
          label: "Synthetic fixture — not for live use", level: "blocked",
          blurb: "A software/statistics fixture only. It can never be used for a live market forecast.",
        };
      default:
        return {
          label: "Limited evidence", level: "limited",
          blurb: "The evidence tier for this model is not established.",
        };
    }
  }

  /*
   * describeLiveState({ gate, drift, sourceHealth, shiftApplied }) ->
   *   { code, label, blurb }
   * Classifies the Live banner without exposing warming/gate/residual terms.
   * Accepts either an options object or the positional (gate, drift, health, shift).
   */
  function describeLiveState(opts, drift, sourceHealth, shiftApplied) {
    var gate, health, shift;
    if (opts && typeof opts === "object") {
      gate = opts.gate; drift = opts.drift; health = opts.sourceHealth; shift = opts.shiftApplied;
    } else {
      gate = opts; health = sourceHealth; shift = shiftApplied;
    }
    var stale = health === "stale" || health === false;

    if (drift) {
      return {
        code: "BASE_ONLY_DRIFT", label: "Drift detected",
        blurb:
          "Recent behavior differs from the data used to validate the live adjustment. " +
          "FinCompass has disabled the adjustment and returned to the base forecast.",
      };
    }
    if (stale) {
      return {
        code: "BASE_ONLY_STALE", label: "Data is stale",
        blurb: "Fresh market information is unavailable. The last validated base forecast is being shown.",
      };
    }
    if (gate === "warming" || gate === "learning") {
      return {
        code: "BASE_ONLY_WARMING", label: "Learning in progress",
        blurb:
          "FinCompass is collecting enough completed outcomes before allowing live adjustments. " +
          "The validated base forecast remains in use.",
      };
    }
    if (gate === "active" && shift) {
      return {
        code: "ACTIVE", label: "Live updates active",
        blurb: "New information can adjust the forecast within validated limits.",
      };
    }
    return {
      code: "BASE_ONLY_DEGRADED", label: "Using base forecast",
      blurb:
        "The live adjustment is currently unavailable or not reliable enough, " +
        "so FinCompass is using the validated base forecast.",
    };
  }

  /*
   * liveStateFromSnapshot(d) -> { code, label, blurb }
   * Classifies a /realtime snapshot into a Guided Live banner. gate.status is
   * "warming" | "degraded" | "active"; drift.alert and source_health.market
   * refine it. Never exposes warming/gate/residual terms.
   */
  function liveStateFromSnapshot(d) {
    d = d || {};
    var gate = d.gate || {};
    var status = gate.status || d.gate_status || "warming";
    var driftAlert = !!(d.drift && d.drift.alert);
    var applied = d.adaptive_shift_applied !== undefined ? !!d.adaptive_shift_applied : !!d.gate_active;
    var sh = d.source_health || {};
    var mkt = (sh.market && sh.market.status) ? String(sh.market.status).toLowerCase() : "";
    var marketStale = mkt && mkt !== "fresh" && mkt !== "ok";

    if (driftAlert) return describeLiveState({ drift: true });
    if (status === "warming") return describeLiveState({ gate: "warming" });
    if (status === "active" && applied) return describeLiveState({ gate: "active", shiftApplied: true });
    if (marketStale) return describeLiveState({ sourceHealth: "stale" });
    return describeLiveState({ gate: "degraded" });
  }

  /*
   * describeProbabilityChange(anchor, applied) ->
   *   { deltaPoints, direction, sentence }
   * Deterministic from the actual applied shift.
   */
  function describeProbabilityChange(anchor, applied) {
    var a = clampProb(anchor);
    var b = clampProb(applied);
    if (a === null || b === null) {
      return { deltaPoints: null, direction: "none", sentence: "No live adjustment is available." };
    }
    var pts = Math.round((b - a) * 100);
    if (pts === 0) {
      return { deltaPoints: 0, direction: "none",
        sentence: "New information has not materially changed the outlook." };
    }
    var dir = pts > 0 ? "up" : "down";
    var verb = pts > 0 ? "increased" : "decreased";
    var mag = Math.abs(pts) <= 2 ? "modestly " : "";
    return {
      deltaPoints: pts, direction: dir,
      sentence: "New information has " + mag + verb + " the estimated chance of outperformance.",
    };
  }

  /*
   * describeDataReadiness(readiness) -> { status, label, action, blurb }
   * `readiness.status`: "ready" | "caution" | "unsupported" | "needs_data".
   */
  function describeDataReadiness(readiness) {
    readiness = readiness || {};
    switch (String(readiness.status || "").toLowerCase()) {
      case "ready":
        return { status: "ready", label: "Ready", action: null,
          blurb: "Enough price history is available and the model applies to this stock." };
      case "needs_data":
        return { status: "needs_data", label: "Needs data", action: "Update data",
          blurb: "Local history is insufficient to build this model's inputs for this stock." };
      case "caution":
        return { status: "caution", label: "Usable with caution", action: null,
          blurb: "This model can run, but review the noted limitation before relying on the result." };
      case "unsupported":
        return { status: "unsupported", label: "Model not suitable", action: null,
          blurb: "This model should not be used for this stock." };
      default:
        return { status: "unknown", label: "Checking…", action: null, blurb: "" };
    }
  }

  /*
   * describeForecastReason(code, data) -> plain sentence for a preflight reason.
   * data carries honest numbers (available_rows, missing, benchmark).
   */
  function describeForecastReason(code, data) {
    data = data || {};
    switch (String(code || "").toUpperCase()) {
      case "NO_ELIGIBLE_MODEL":
        return "FinCompass does not yet have a validated model for this market and forecast period.";
      case "BENCHMARK_UNAVAILABLE":
        return "Price history for the benchmark (" + friendlyBenchmark(data.benchmark) +
          ") is not available locally, so the comparison cannot be measured.";
      case "INSUFFICIENT_HISTORY":
        return "There is not enough local price history for this stock to build the model's inputs" +
          (data.available_rows != null ? " (" + data.available_rows + " rows available)." : ".");
      case "SEC_FEATURES_REQUIRED":
        return "This model needs point-in-time SEC filing data, which is not configured in this install.";
      case "FEATURES_UNAVAILABLE":
        return "Some inputs this model requires could not be built for this stock.";
      case "UNSUPPORTED_ASSET_CLASS":
        return "This model was validated on " + (data.supported || ["equity"]).join("/") +
          " instruments; " + (data.asset_class || "this instrument") + " is not supported.";
      case "UNSUPPORTED_REGION":
        return "This model was validated on " + (data.supported || ["US"]).join("/") +
          " markets; the " + (data.region || "this") + " market is not supported.";
      case "UNSUPPORTED_SECURITY_TYPE":
        return "This model was validated on individual company stocks, not " +
          (data.security_type || "this security type") + "s.";
      case "BENCHMARK_MISMATCH":
        return "A reliable benchmark for this instrument's market differs from the model's, " +
          "so FinCompass will not compare them.";
      case "MODEL_DOMAIN_UNKNOWN":
        return "The model's supported market is not documented, so FinCompass cannot confirm it applies here.";
      case "INSTRUMENT_CLASSIFICATION_UNAVAILABLE":
        return "FinCompass could not identify this instrument's market and type, so it cannot confirm a model applies.";
      case "OUTSIDE_MODEL_DOMAIN":
        return "This instrument is outside the model's validated domain.";
      case "PREFLIGHT_ERROR":
      case "INFERENCE_ERROR":
      case "MODEL_LOAD_ERROR":
        return "FinCompass could not complete this forecast right now. Please try again.";
      default:
        return "This model cannot produce a reliable forecast for this stock right now.";
    }
  }

  // Full preflight contract -> Guided decision. A forecast is allowed only when
  // all three flags are true (data + computational + scientific).
  function describeForecastPreflight(preflight) {
    preflight = preflight || {};
    var canRun = !!(preflight.data_ready && preflight.computationally_compatible && preflight.scientifically_supported);
    var reasons = [];
    var seen = {};
    (preflight.reasons || []).forEach(function (r) {
      var t = describeForecastReason(r.code, r.message_data);
      if (!seen[t]) { seen[t] = true; reasons.push(t); }
    });
    var noModel = (preflight.reasons || []).some(function (r) { return r.code === "NO_ELIGIBLE_MODEL"; });
    var readiness = describeDataReadiness({
      status: preflight.status === "ready" ? "ready" : (preflight.status === "needs_data" ? "needs_data" : "unsupported"),
    });
    var bp = preflight.benchmark_policy || {};
    return {
      status: preflight.status, canRun: canRun, reasons: reasons, noModel: noModel,
      label: readiness.label, action: readiness.action,
      benchmarkName: bp.benchmark_name || null,
      flags: {
        data_ready: !!preflight.data_ready,
        computationally_compatible: !!preflight.computationally_compatible,
        scientifically_supported: !!preflight.scientifically_supported,
      },
    };
  }

  // Plain language for a scientific gate that a trained candidate failed.
  var GATE_MESSAGES = {
    roc_auc: "The model did not rank future winners and losers reliably enough.",
    bootstrap_auc_low: "The model did not rank future winners and losers reliably enough.",
    brier_skill: "Its probability estimates were not better than the reference forecast.",
    bootstrap_brier_skill_low: "Its probability estimates were not better than the reference forecast.",
    log_loss_skill: "Its probability estimates were not sharp enough versus the reference forecast.",
    bootstrap_log_loss_skill_low: "Its probability estimates were not sharp enough versus the reference forecast.",
    ece: "Probabilities such as 60% or 70% did not behave consistently enough in held-out data.",
    bootstrap_ece_high: "Probabilities such as 60% or 70% did not behave consistently enough in held-out data.",
    calibration_slope: "Probabilities such as 60% or 70% did not behave consistently enough in held-out data.",
    walk_forward_stability: "Performance was not stable enough across different historical periods.",
  };

  function describeGateFailure(code) {
    return GATE_MESSAGES[String(code || "").toLowerCase()] ||
      "This model did not meet one of the validation requirements.";
  }

  // Collapse a set of failed-gate codes to a short, de-duplicated plain-language list.
  function describeGateFailures(codes) {
    var seen = {}, out = [];
    (codes || []).forEach(function (c) {
      var msg = describeGateFailure(c);
      if (!seen[msg]) { seen[msg] = true; out.push(msg); }
    });
    return out;
  }

  /*
   * describeTrainingFailure(reasonCode, details) -> { title, blurb }
   * Distinguishes NOT_READY / TRAINING_FAILED / REJECTED.
   */
  function describeTrainingFailure(reasonCode, details) {
    switch (String(reasonCode || "").toUpperCase()) {
      case "NOT_READY":
        return { title: "Not enough data to start training",
          blurb: "The data requirements for this recipe are not met yet. Update the missing data, then train." };
      case "TRAINING_FAILED":
        return { title: "Training could not complete",
          blurb: "A software or numerical error stopped training. This is not a model-quality result." };
      case "REJECTED":
        return { title: "Training completed, but the model did not pass",
          blurb: "The model trained successfully but failed the validation requirements. FinCompass will not activate it." };
      default:
        return { title: "Training did not produce a usable model", blurb: "" };
    }
  }

  /*
   * describeExperimentOutcome(status, tier, failedGates) -> { kind, title, blurb, reasons }
   * Distinguishes not-ready (data) / failed (software) / rejected (science) /
   * validated so a rejection never reads as a crash.
   */
  function describeExperimentOutcome(status, tier, failedGates) {
    switch (String(status || "").toLowerCase()) {
      case "validated": {
        var t = describeModelTier(tier);
        return { kind: "validated", title: "Validated — ready to activate",
          blurb: t.label + ". Not active until you explicitly activate it.", reasons: [] };
      }
      case "rejected": {
        var f = describeTrainingFailure("REJECTED");
        return { kind: "rejected", title: f.title, blurb: f.blurb,
          reasons: describeGateFailures(failedGates) };
      }
      case "not_ready": {
        var nr = describeTrainingFailure("NOT_READY");
        return { kind: "not_ready", title: nr.title, blurb: nr.blurb, reasons: [] };
      }
      case "failed": {
        var tf = describeTrainingFailure("TRAINING_FAILED");
        return { kind: "failed", title: tf.title, blurb: tf.blurb, reasons: [] };
      }
      case "training":
      case "candidate":
        return { kind: "progress", title: "Training in progress", blurb: "", reasons: [] };
      default:
        return { kind: "unknown", title: String(status || "unknown"), blurb: "", reasons: [] };
    }
  }

  // Ordered training stages for the progress indicator. No fake percent.
  var TRAINING_STAGES = [
    { key: "checking_data", label: "Checking data" },
    { key: "building_examples", label: "Building examples" },
    { key: "training_models", label: "Training models" },
    { key: "calibrating", label: "Calibrating probabilities" },
    { key: "locked_test", label: "Running locked test" },
    { key: "checking_gates", label: "Checking validation gates" },
    { key: "saving_candidate", label: "Saving candidate" },
  ];

  // describeTrainingStages(phase) -> [{label, state: 'done'|'active'|'todo'}]
  function describeTrainingStages(phase) {
    var order = TRAINING_STAGES.map(function (s) { return s.key; });
    // training_models covers the internal calibrate/locked-test work in one call;
    // treat those as reached once training has started.
    var idx = order.indexOf(String(phase || ""));
    if (String(phase) === "queued") idx = -1;
    if (String(phase) === "complete") idx = order.length;
    if (String(phase) === "training_models") idx = order.indexOf("locked_test"); // through the internal stages
    return TRAINING_STAGES.map(function (s, i) {
      return { label: s.label, state: i < idx ? "done" : (i === idx ? "active" : "todo") };
    });
  }

  // describeReadiness(result) -> { ready, headline, checklist:[{label,ok}], actions:[...] }
  function describeReadiness(result) {
    result = result || {};
    var ready = !!result.ready;
    var checklist = (result.checklist || []).map(function (c) {
      return { label: c.label, ok: c.status === "pass" };
    });
    var actions = [];
    var seen = {};
    (result.gates || []).forEach(function (g) {
      var line = g.explanation + (g.action ? " " + g.action : "");
      if (!seen[line]) { seen[line] = true; actions.push({ code: g.code, text: line, symbols: g.symbols || [] }); }
    });
    return {
      ready: ready,
      headline: ready ? "Ready to train" : "Data needs attention",
      checklist: checklist,
      actions: actions,
    };
  }

  // Plain instrument identity line (step 1). Provider metadata stays hidden.
  function describeInstrument(inst) {
    inst = inst || {};
    var name = inst.name || inst.symbol || "";
    var bits = [];
    if (inst.security_type && inst.security_type !== "unknown") bits.push(inst.security_type);
    if (inst.exchange) bits.push(inst.exchange);
    if (inst.country && inst.country !== inst.region) bits.push(inst.country);
    else if (inst.region) bits.push(inst.region);
    return { title: name, subtitle: bits.join(" · ") };
  }

  // Model-freshness banner (step 3 / model status).
  function describeFreshness(fr) {
    fr = fr || {};
    var lagMo = fr.model_data_lag_months;
    switch (String(fr.status || "").toLowerCase()) {
      case "current":
        return { level: "ok", label: "Model current",
          blurb: "Training includes market information through " + (fr.training_cutoff || "its cutoff") + "." };
      case "update_recommended":
        return { level: "warn", label: "Update recommended",
          blurb: "Newer market information is available — this model was trained through " +
            (fr.training_cutoff || "an earlier date") +
            (lagMo != null ? " (about " + Math.round(lagMo) + " months behind today's market)" : "") +
            ". The current forecast can still be viewed; retraining is recommended." };
      case "stale":
        return { level: "bad", label: "Model out of date",
          blurb: "This model was trained through " + (fr.training_cutoff || "an old date") +
            (lagMo != null ? "; about " + Math.round(lagMo) + " months of market behavior are not represented" : "") +
            ". Update the model before relying on a new forecast." };
      default:
        return { level: "muted", label: "Model status unknown", blurb: "" };
    }
  }

  // Evidence strength from validation metrics (deterministic mapping).
  function describeEvidenceStrength(metrics) {
    metrics = metrics || {};
    var auc = Number(metrics.roc_auc);
    var brierSkill = Number(metrics.brier_skill);
    if (!isFinite(auc)) return { label: "Limited evidence", level: "limited" };
    if (auc >= 0.60 && isFinite(brierSkill) && brierSkill >= 0.03)
      return { label: "Stronger evidence", level: "stronger" };
    if (auc >= 0.55)
      return { label: "Moderate evidence", level: "moderate" };
    return { label: "Limited evidence", level: "limited" };
  }

  global.FCP = {
    describeInstrument: describeInstrument,
    describeFreshness: describeFreshness,
    describeEvidenceStrength: describeEvidenceStrength,
    describeTrainingStages: describeTrainingStages,
    describeReadiness: describeReadiness,
    describeExperimentOutcome: describeExperimentOutcome,
    pctWord: pctWord,
    horizonWords: horizonWords,
    friendlyBenchmark: friendlyBenchmark,
    describeEventCategory: describeEventCategory,
    liveStateFromSnapshot: liveStateFromSnapshot,
    describeEvent: describeEvent,
    describeForecastProbability: describeForecastProbability,
    describeModelTier: describeModelTier,
    describeLiveState: describeLiveState,
    describeProbabilityChange: describeProbabilityChange,
    describeDataReadiness: describeDataReadiness,
    describeForecastReason: describeForecastReason,
    describeForecastPreflight: describeForecastPreflight,
    describeGateFailure: describeGateFailure,
    describeGateFailures: describeGateFailures,
    describeTrainingFailure: describeTrainingFailure,
  };
})(typeof window !== "undefined" ? window : this);
