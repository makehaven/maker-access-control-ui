/* Vendored from makehaven/makerspace_kiosk (91cf902). Keep in step with the website copy; do not edit here. */
/**
 * @file
 * Shared resilience runtime for unattended kiosk displays.
 *
 * These pages run on wall-mounted Raspberry Pis for months without a keyboard.
 * Nothing external recovers them, so every failure has to be either survived or
 * made visible to a human walking past. The rules this encodes:
 *
 * 1. A stale board must never look like a live one. Silent staleness is the
 *    worst failure mode we have - a frozen member-faces grid is indistinguishable
 *    from a working one, so nobody reports it.
 * 2. Never reload into a broken world. A reload that lands on a browser error
 *    page strands the kiosk with no JS left to retry, which is strictly worse
 *    than staying up on stale data and continuing to poll. Every reload is gated
 *    on a probe that proves the site is answering first.
 * 3. Back off when the site is down. Hammering a deploying site at 30s intervals
 *    helps nobody and bills us for the privilege (Pantheon counts CDN hits).
 * 4. De-synchronise the fleet. Screens reboot on the same cron and poll on the
 *    same fixed intervals, so they converge into a thundering herd. Jitter
 *    everything.
 */
(function (window, document) {
  'use strict';

  var DEFAULTS = {
    // Where to poll, and how to identify this screen in the logs.
    // feedUrl may be a function returning a URL, for incremental feeds whose
    // query string depends on what the board has already seen.
    feedUrl: null,
    screenId: null,

    // Base cadence. Actual delay is jittered by +/- jitterRatio so that six
    // screens that booted together do not line up forever.
    intervalMs: 30000,
    jitterRatio: 0.1,

    // On failure, back off geometrically to maxBackoffMs instead of retrying at
    // the base cadence. A Pantheon deploy is over in well under five minutes.
    backoffFactor: 2,
    maxBackoffMs: 300000,

    // Show the degraded state once data is this old. Defaults to 6x the base
    // interval, i.e. roughly five missed polls, which is past "one blip".
    staleAfterMs: null,

    // Probe-gated reload after this many consecutive failures. Only network-
    // level failures count; see shouldCountAsFailure().
    reloadAfterFailures: 10,

    // Minimum gap between recovery reloads, persisted across the reload itself.
    // Without this a broken feed behind a healthy page reload-loops forever:
    // the reload fixes nothing, failures re-accumulate, and the board flickers
    // while billing us a page load every few minutes. One attempt per window is
    // enough to rescue a genuinely wedged tab.
    reloadCooldownMs: 900000,
    reloadCooldownKey: 'mk:lastRecoveryReload',

    // A tab whose timers have been suspended (or whose JS has wedged) will not
    // tick. If wall-clock time since the loop was last alive exceeds
    // wedgeFactor x interval, treat the tab as wedged and recover.
    //
    // "Alive" means a tick STARTED, not that one finished. A request still in
    // flight is a healthy loop waiting on a slow server, and reloading it mid-
    // request is exactly the wrong move during the outage that made it slow.
    wedgeFactor: 4,

    // Hard ceiling on a single feed request. fetch() has no default timeout, so
    // a connection that opens and then hangs - a half-dead server, a captive
    // portal, a Pi that lost its route - would stall the loop forever behind
    // the overlap guard. This is what actually makes the wedge watchdog a
    // last resort rather than the first line of defence.
    requestTimeoutMs: 20000,

    // Hard reload once a day at this local hour, so a tab leaking memory never
    // runs for weeks. Jittered across the hour so the fleet does not reload in
    // lockstep. Set to null to disable.
    dailyReloadHour: 4,

    // Inject the corner status chip (clock + freshness + state).
    statusChip: true,
    statusChipPosition: 'bottom-right',

    // Callbacks.
    onData: null,   // (data, ctx) - render. Throwing here counts as a failure.
    onError: null,  // ({ kind, status, error, consecutiveFailures })
    onStale: null,  // ({ stale, lastSuccessAt, ageMs })
    onRecover: null // ()
  };

  /**
   * Applies +/- ratio jitter to a delay.
   */
  function jitter(ms, ratio) {
    if (!ratio) {
      return ms;
    }
    var spread = ms * ratio;
    return Math.max(1000, Math.round(ms - spread + (Math.random() * spread * 2)));
  }

  function pad(n) {
    return n < 10 ? '0' + n : '' + n;
  }

  function clockText(d) {
    return pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  /**
   * Human-readable age, deliberately coarse - this is glanced at from across a
   * room, not read.
   */
  function ageText(ms) {
    if (ms < 60000) {
      return 'just now';
    }
    var mins = Math.floor(ms / 60000);
    if (mins < 60) {
      return mins + 'm ago';
    }
    var hours = Math.floor(mins / 60);
    if (hours < 24) {
      return hours + 'h ago';
    }
    return Math.floor(hours / 24) + 'd ago';
  }

  /**
   * Distinguishes "the site answered, badly" from "we could not reach it".
   *
   * A 5xx during a deploy means the host is up and will be back shortly: keep
   * showing the last good render and back off. A network-level failure may mean
   * the tab itself is wedged, which is the case a reload can actually fix. Only
   * the latter counts toward the reload threshold.
   */
  function shouldCountAsFailure(kind) {
    return kind === 'network';
  }

  function buildStatusChip(position) {
    var chip = document.createElement('div');
    chip.className = 'mk-status mk-status--' + position;
    chip.setAttribute('role', 'status');
    chip.innerHTML =
      '<span class="mk-status__dot"></span>' +
      '<span class="mk-status__clock"></span>' +
      '<span class="mk-status__age"></span>';
    return chip;
  }

  /**
   * Starts a resilient polling loop. Returns a small controller so callers can
   * force a tick or shut the loop down in tests.
   */
  function start(userOptions) {
    var o = {};
    var key;
    for (key in DEFAULTS) {
      if (Object.prototype.hasOwnProperty.call(DEFAULTS, key)) {
        o[key] = DEFAULTS[key];
      }
    }
    for (key in userOptions) {
      if (Object.prototype.hasOwnProperty.call(userOptions, key)) {
        o[key] = userOptions[key];
      }
    }

    if (!o.feedUrl) {
      throw new Error('MakerspaceKiosk.start: feedUrl is required');
    }
    if (o.staleAfterMs === null) {
      o.staleAfterMs = o.intervalMs * 6;
    }

    var state = {
      lastSuccessAt: null,
      lastLoopAt: Date.now(),
      consecutiveFailures: 0,
      currentDelay: o.intervalMs,
      stale: false,
      stopped: false,
      fetching: false
    };

    var chip = null;
    var chipDot = null;
    var chipClock = null;
    var chipAge = null;

    if (o.statusChip) {
      chip = buildStatusChip(o.statusChipPosition);
      chipDot = chip.querySelector('.mk-status__dot');
      chipClock = chip.querySelector('.mk-status__clock');
      chipAge = chip.querySelector('.mk-status__age');
      // Append once the body exists; these controllers emit the script inline
      // at the end of <body>, but guard anyway.
      if (document.body) {
        document.body.appendChild(chip);
      }
      else {
        document.addEventListener('DOMContentLoaded', function () {
          document.body.appendChild(chip);
        });
      }
    }

    /**
     * The chip is the whole answer to "is this board alive?". A ticking clock
     * proves JS is running; the age proves the data is fresh. Staff can triage
     * from the doorway: frozen clock means dead tab, stale age means dead feed.
     */
    function paintChip() {
      if (!chip) {
        return;
      }
      var now = Date.now();
      chipClock.textContent = clockText(new Date(now));
      if (state.lastSuccessAt === null) {
        chipAge.textContent = 'connecting';
        chip.className = 'mk-status mk-status--' + o.statusChipPosition + ' is-connecting';
        return;
      }
      var age = now - state.lastSuccessAt;
      if (state.stale) {
        // "just now" next to a red warning light is a contradiction a tired
        // staff member has to decode. Name the actual last-good time instead -
        // it is the one fact that makes the failure actionable.
        chipAge.textContent = 'no update since ' + clockText(new Date(state.lastSuccessAt));
      }
      else {
        chipAge.textContent = ageText(age);
      }
      chip.className = 'mk-status mk-status--' + o.statusChipPosition + (state.stale ? ' is-stale' : ' is-ok');
    }

    function setStale(stale) {
      if (stale === state.stale) {
        return;
      }
      state.stale = stale;
      paintChip();
      if (stale && typeof o.onStale === 'function') {
        o.onStale({
          stale: true,
          lastSuccessAt: state.lastSuccessAt,
          ageMs: state.lastSuccessAt ? Date.now() - state.lastSuccessAt : null
        });
      }
      if (!stale && typeof o.onRecover === 'function') {
        o.onRecover();
      }
    }

    /**
     * Reads the last recovery-reload timestamp. Persisted in sessionStorage so
     * it survives the reload it is rate-limiting - an in-memory counter would be
     * wiped by the very thing it exists to bound. Kiosks are single-tab and
     * never navigate away, so sessionStorage is exactly the right lifetime.
     */
    function lastReloadAt() {
      try {
        var raw = window.sessionStorage.getItem(o.reloadCooldownKey);
        return raw ? parseInt(raw, 10) || 0 : 0;
      }
      catch (e) {
        // Private mode or a locked-down browser profile. Degrade to "no memory
        // of prior reloads" rather than losing recovery entirely.
        return 0;
      }
    }

    function markReloaded() {
      try {
        window.sessionStorage.setItem(o.reloadCooldownKey, String(Date.now()));
      }
      catch (e) { /* See lastReloadAt(). */ }
    }

    /**
     * Reloads only once a HEAD probe proves the site is answering, and only if
     * we have not already tried recently.
     *
     * Two distinct traps this avoids. Reloading blind while the network is down
     * replaces a stale-but-live kiosk with a browser error page that has no JS
     * left to retry. And reloading repeatedly when the page is healthy but the
     * feed is not turns a broken endpoint into a permanent reload loop, which
     * fixes nothing and costs a page load every cycle.
     */
    function probeAndReload(reason, options) {
      var force = options && options.force;
      if (!force && o.reloadCooldownMs) {
        var since = Date.now() - lastReloadAt();
        if (since < o.reloadCooldownMs) {
          if (window.console && console.info) {
            console.info('[kiosk] reload suppressed (' + Math.round(since / 1000) + 's into cooldown):', reason);
          }
          return;
        }
      }
      fetch(window.location.href, { method: 'HEAD', cache: 'no-store' })
        .then(function (r) {
          if (r.ok) {
            if (window.console && console.warn) {
              console.warn('[kiosk] probe passed, reloading:', reason);
            }
            markReloaded();
            window.location.reload();
          }
        })
        .catch(function () { /* Still down. Stay up and keep polling. */ });
    }

    function feedUrlWithScreen() {
      var url = typeof o.feedUrl === 'function' ? o.feedUrl() : o.feedUrl;
      if (!url) {
        throw new Error('feedUrl resolved to nothing');
      }
      if (!o.screenId) {
        return url;
      }
      // Ride along on a request we were making anyway, so the server can record
      // last-seen per screen without any extra polling traffic.
      var sep = url.indexOf('?') === -1 ? '?' : '&';
      return url + sep + 'screen=' + encodeURIComponent(o.screenId);
    }

    function handleFailure(kind, status, error) {
      if (shouldCountAsFailure(kind)) {
        state.consecutiveFailures++;
      }
      state.currentDelay = Math.min(state.currentDelay * o.backoffFactor, o.maxBackoffMs);

      if (typeof o.onError === 'function') {
        try {
          o.onError({
            kind: kind,
            status: status || null,
            error: error || null,
            consecutiveFailures: state.consecutiveFailures
          });
        }
        catch (e) {
          if (window.console) {
            console.error('[kiosk] onError threw', e);
          }
        }
      }

      if (o.reloadAfterFailures && state.consecutiveFailures >= o.reloadAfterFailures) {
        state.consecutiveFailures = 0;
        probeAndReload('consecutive network failures');
      }
    }

    async function tick() {
      if (state.stopped || state.fetching) {
        return;
      }
      state.fetching = true;
      // Stamp liveness on entry: the loop is running, whatever the server does
      // next. Stamping only on completion made a slow feed indistinguishable
      // from a dead tab, and the watchdog reloaded mid-request.
      state.lastLoopAt = Date.now();

      var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      var timeout = controller ? window.setTimeout(function () { controller.abort(); }, o.requestTimeoutMs) : null;

      try {
        var fetchOptions = { cache: 'no-store' };
        if (controller) {
          fetchOptions.signal = controller.signal;
        }
        var response = await fetch(feedUrlWithScreen(), fetchOptions);
        if (!response.ok) {
          // The host answered. It is deploying, rate-limiting, or misconfigured
          // - all cases where the last good render is the best thing on screen.
          handleFailure('http', response.status, null);
          return;
        }
        var data = await response.json();

        if (typeof o.onData === 'function') {
          // A render that throws is a real failure: the board is now showing
          // something wrong. Treat it like a bad payload rather than swallowing.
          o.onData(data, { stale: state.stale });
        }

        state.lastSuccessAt = Date.now();
        state.consecutiveFailures = 0;
        state.currentDelay = o.intervalMs;
        setStale(false);
      }
      catch (error) {
        // fetch() rejects on DNS/offline/CORS; JSON.parse and onData throw here
        // too. All of them mean this tab is not currently able to show truth.
        handleFailure('network', null, error);
      }
      finally {
        if (timeout !== null) {
          window.clearTimeout(timeout);
        }
        state.fetching = false;
        state.lastLoopAt = Date.now();
        paintChip();
      }
    }

    var timer = null;

    function schedule() {
      if (state.stopped) {
        return;
      }
      if (timer) {
        window.clearTimeout(timer);
      }
      // setTimeout recursion rather than setInterval: backoff has to be able to
      // change the delay, and overlapping ticks on a slow feed would stack.
      timer = window.setTimeout(function () {
        tick().then(schedule, schedule);
      }, jitter(state.currentDelay, o.jitterRatio));
    }

    // Second-resolution chip repaint and staleness check. Independent of the
    // poll loop on purpose: if the poll loop dies, the clock keeps ticking and
    // the age keeps climbing, which is exactly the signal we want on screen.
    var supervisor = window.setInterval(function () {
      if (state.stopped) {
        return;
      }
      var now = Date.now();

      if (state.lastSuccessAt !== null) {
        setStale(now - state.lastSuccessAt > o.staleAfterMs);
      }
      paintChip();

      // Wedge detection: wall-clock time, not timer count, so it survives a tab
      // whose timers were throttled or suspended by the browser. Never fires
      // while a request is in flight - that is a live loop, not a wedged one,
      // and requestTimeoutMs bounds how long it can stay that way.
      if (!state.fetching) {
        var sinceLoop = now - state.lastLoopAt;
        var wedgeAfter = Math.max(o.intervalMs, state.currentDelay) * o.wedgeFactor
          + o.requestTimeoutMs;
        if (sinceLoop > wedgeAfter) {
          state.lastLoopAt = now;
          probeAndReload('poll loop stopped for ' + Math.round(sinceLoop / 1000) + 's');
        }
      }
    }, 1000);

    // Daily hard reload at a fixed local hour, jittered across it so the fleet
    // does not all reload at once. Anchored to wall-clock rather than "24h after
    // boot", which drifts into the middle of the day.
    var dailyGuard = null;
    if (o.dailyReloadHour !== null && o.dailyReloadHour !== undefined) {
      var reloadMinute = Math.floor(Math.random() * 60);
      dailyGuard = window.setInterval(function () {
        var d = new Date();
        if (d.getHours() === o.dailyReloadHour && d.getMinutes() === reloadMinute) {
          // Maintenance, not failure recovery: exempt from the cooldown.
          probeAndReload('scheduled daily reload', { force: true });
        }
      }, 60000);
    }

    // A kiosk tab that was suspended (HDMI input switched away, display asleep)
    // comes back with stale data. Poll immediately rather than waiting out the
    // remaining delay.
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && !state.stopped) {
        tick().then(schedule, schedule);
      }
    });
    window.addEventListener('online', function () {
      if (!state.stopped) {
        state.currentDelay = o.intervalMs;
        tick().then(schedule, schedule);
      }
    });

    paintChip();
    tick().then(schedule, schedule);

    return {
      tickNow: function () {
        return tick().then(schedule, schedule);
      },
      state: function () {
        return {
          lastSuccessAt: state.lastSuccessAt,
          consecutiveFailures: state.consecutiveFailures,
          currentDelay: state.currentDelay,
          stale: state.stale
        };
      },
      stop: function () {
        state.stopped = true;
        window.clearTimeout(timer);
        window.clearInterval(supervisor);
        if (dailyGuard) {
          window.clearInterval(dailyGuard);
        }
      }
    };
  }

  window.MakerspaceKiosk = {
    start: start,
    // Exported for unit tests.
    _internals: {
      jitter: jitter,
      ageText: ageText,
      shouldCountAsFailure: shouldCountAsFailure
    }
  };
})(window, document);
