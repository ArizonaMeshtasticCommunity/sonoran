/*
 * The words the weekly check-in page puts next to a person's name.
 *
 * `docs/design/2026-09-26-ux-overhaul.md` §6.3. The arithmetic is not
 * here: a streak is a windowed aggregate over weeks and is computed by
 * `api/chat/tagged`, because the page's own window is 4, 8 or 26 weeks
 * and a run is longer than whichever of those somebody happened to
 * pick. A browser that counted the weeks it was sent would report a run
 * of 30 as 8 and call it a measurement.
 *
 * What IS here is every decision about how a number becomes a sentence,
 * and that is a separate job worth its own file because this page makes
 * claims about people rather than radios. The plan's own risk note:
 * "getting it wrong is worse here than on any other page in the brief".
 *
 * Two rules run through all of it.
 *
 * **A missing value is not a zero.** `Number(null)` is 0, `null >= 0` is
 * true, and `${undefined}` is a string that renders. Five bugs in this
 * repository have been a missing figure drawn as a real one. Every entry
 * point below asks `Number.isInteger` before it will print a count, and
 * says the count is not known otherwise. "Not measured" and "measured,
 * and it is nothing" are different sentences and must never share one.
 *
 * **An absence is an observation, not a verdict.** A node that did not
 * post may have been off, out of range, or its message may not have been
 * stored at all. So the words are "no message found", never "missed",
 * and an unfinished week is never described as a broken anything.
 */
window.SonoranMeshnet = (function build() {
  /*
   * A count that may not exist.
   *
   * `check_in_count` and `streak_weeks` both come off the wire, and both
   * are absent on a response from an older server. `Number(value)` would
   * turn that absence into 0 and the page would state it as a fact.
   * Anything that is not a whole number is not a count.
   */
  function counted(value) {
    return Number.isInteger(value) ? value : null;
  }

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  /*
   * How a streak reads beside somebody's name.
   *
   * The `+` is load-bearing. The server reads a fixed number of weeks
   * back; a run that reaches the bottom of that read has no measured
   * beginning, so `streak_at_least` says the number is a floor. Printing
   * "52 weeks in a row" for a run that might be 104 is a smaller lie
   * than printing it for a run that might be 52, and both are avoidable.
   */
  function streakWord(entry) {
    const weeks = counted(entry && entry.streak_weeks);
    // Zero next to a check-in is a contradiction: the node is on this
    // list because it posted, so its run is at least 1. A server that
    // sends 0 here is wrong about something, and the honest answer is to
    // say the streak is not known rather than to print "0 weeks".
    if (weeks == null || weeks < 1) return 'Streak not known';
    const more = entry.streak_at_least ? '+' : '';
    if (weeks === 1 && !more) {
      // A run of one is either a beginning or a restart, and those read
      // completely differently to somebody scanning the list.
      return entry.first_ever ? 'First check-in' : 'Back after a gap';
    }
    return `${weeks}${more} weeks in a row`;
  }

  /** The longer explanation for the same chip, or null. */
  function streakDetail(entry, floorWeek) {
    const weeks = counted(entry && entry.streak_weeks);
    if (weeks == null || weeks < 1) {
      return 'The server did not send a streak for this check-in.';
    }
    if (!entry.streak_at_least) {
      return `Checked in every week for ${plural(weeks, 'week', 'weeks')} up to and including this one.`;
    }
    const since = floorWeek ? ` The read starts at ${floorWeek}, so the run may be longer.` : '';
    return `Checked in every one of the ${plural(weeks, 'week', 'weeks')} this read covers.${since}`;
  }

  /*
   * The words for a node that checked in last week and not this one.
   *
   * `inProgress` is the whole reason this takes two arguments. The
   * current week has not finished, so nothing about it is a verdict: a
   * node with no message yet has broken nothing and its run is still
   * open. Reporting that as a broken streak would mark most of the mesh
   * as lapsed every Monday morning.
   */
  function absenceWord(entry, inProgress) {
    const weeks = counted(entry && entry.streak_weeks);
    const more = entry && entry.streak_at_least ? '+' : '';
    /*
     * "A run of 1 weeks" is what the first draft printed on the live
     * page, and a page that cannot count to one is not going to be
     * believed about counting to thirty. A bounded run always reads as
     * plural, because "1+ week" would be claiming a run of exactly one.
     */
    const run = weeks == null || weeks < 1
      ? null
      : `${weeks}${more} ${weeks === 1 && !more ? 'week' : 'weeks'}`;
    const perhaps = 'The node may have been off, out of range, or its message may not have been '
      + 'stored.';
    if (inProgress) {
      return {
        tone: 'pending',
        text: 'No message yet this week',
        detail: run
          ? `A run of ${run} is still open. This week is not over.`
          : 'This week is not over.',
      };
    }
    return {
      tone: 'broken',
      text: 'No message found this week',
      detail: run ? `A run of ${run} ends here. ${perhaps}` : perhaps,
    };
  }

  /*
   * The count line on a week's heading.
   *
   * Three outcomes, and they are three different sentences:
   *
   * - the server did not send a count, so nothing is claimed;
   * - the count is zero, which is a measurement and says so;
   * - the count is a number.
   *
   * The middle one used to be invisible: a week nobody checked in was
   * simply absent from the list, which reads as a week that never
   * happened rather than a week with a gap in it.
   */
  function weekWord(week) {
    const nodes = counted(week && week.check_in_count);
    const messages = counted(week && week.message_count);
    if (nodes == null) return 'Check-ins not counted for this week';
    const yet = week && week.in_progress ? ' so far' : '';
    if (nodes === 0) return `No check-in found${yet}`;
    const who = `${plural(nodes, 'node', 'nodes')} checked in${yet}`;
    return messages == null ? who : `${who}, ${plural(messages, 'message', 'messages')}`;
  }

  /*
   * Why the page has nothing to say, when it has nothing to say.
   *
   * The plan flagged this as its own risk: message text storage can be
   * off entirely, in which case there will never be a check-in to find
   * and "nobody checked in" would be a lie told by an empty list. The
   * server answers whether it is keeping bodies (`text_storage`) and
   * whether it could assess anything at all (`streaks`), and those two
   * make three distinguishable outcomes rather than one blank page.
   *
   * Returns null when the page does have something to draw.
   */
  function noAssessmentWord(data) {
    if (!data) return 'The check-in data could not be read.';
    if (data.streaks) return null;
    if (data.text_storage === false) {
      return 'Message text is not being stored, so no check-in can be read. This is not a count of '
        + 'check-ins: it is a setting on the ingest.';
    }
    return 'No check-in could be assessed, and the reason was not reported.';
  }

  /** Whether a week's message list is shorter than the week's own count. */
  function messagesTruncated(week) {
    const shown = counted(week && week.messages_shown);
    const total = counted(week && week.message_count);
    if (shown == null || total == null) return false;
    return shown < total;
  }

  return {
    counted, streakWord, streakDetail, absenceWord, weekWord, noAssessmentWord, messagesTruncated,
  };
}());
