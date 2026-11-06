# Launch posts: drafts for you to edit and send

**Nothing here has been posted.** Checkout is open. Each post leads with something free: the bye
planner or the free report. The plan is one line under it. Read "When to post" first, because the
day decides which one works.

## When to post (ET)

- **The bye planner: any day.** It answers the moment someone pastes a roster. It has byes to find
  through Week 14.
- **The free report and the plan: Tuesday morning to Thursday afternoon.** In that window, someone
  who asks gets this week's lineup, usually within the hour. Tuesday morning means once Monday
  night's game is scored.
- **Not the free report on Wednesday daytime.** Paid reports go out first that day, so a free
  request waits for the evening run.
- **Why not Thursday night to Monday.** This week's games have started. A free request waits until
  Tuesday morning. A buyer gets a roster report when they pay and their first lineup Wednesday
  evening. Both are honest, but nobody gets a lineup the day they read your post.
- At most 40 free reports go out a day. If a post brings more, the rest go the next day.

## The post to pin on X

Pin the bye planner post (section 4). It's true any day, and it never needs editing. PLAN §5 used
to say to pin this week's sample report instead. That page changes every Wednesday, and some weeks
the site doesn't link it at all (Weeks 8 and 9 of 2026, when its lineup had no projected total).
After Week 14's byes, the planner has nothing left to find. Pin the free report post (section 5)
then. Its words are true any day: a request from Thursday night to Monday
gets next week's report.

## Make a link for each post

Make it once, right before you post. Each tag counts on its own row in the dashboard, and a reused
tag is refused:

```bash
make link TAG=league-nov10 WHERE="my league chat" PAGE=byes/
```

```bash
make link TAG=league-nov10-free WHERE="my league chat" PAGE='join/?try=1'
```

```bash
make link TAG=discord-nov10 WHERE="server name" PAGE=byes/
```

```bash
make link TAG=x-pin WHERE="pinned post" PAGE=byes/
```

```bash
make link TAG=x-nov10-free WHERE="X post" PAGE='join/?try=1'
```

`PAGE='join/?try=1'` is the free report. Keep the quotes: without them zsh reads the `?` as a
wildcard and stops.

**Ground rules (PLAN §5).** Reddit: no links in posts or comments, read each sub's rules, ask the
mods first. Discord: ask a mod before posting. X: the link goes in the first reply. Say you built
it. Never post a win-loss record, and no results or promises.

---

## 1. Your own league chat (start here)

Any day:

> I built a free bye week checker. Paste your roster and it shows every week you'd have an empty
> starting spot from here to Week 17. No email, no signup, takes a minute.
>
> [planner link]

Tuesday morning to Thursday afternoon, add:

> I also built the paid version: one email every Wednesday that decides your lineup for your roster.
> Get a free report on your own roster: [free report link]

## 2. Discord: the message to the mod

> Hey, I built a small free tool: paste your fantasy roster and it shows which weeks byes leave you
> with an empty starting spot through Week 17. No signup. Okay if I share it in your server? I also
> make a paid weekly lineup report, and I won't mention that unless you're fine with it.

## 3. Discord: the post, once the mod says yes

> Free bye week check for anyone heading into the playoff push. Paste your roster, see the weeks
> you'd have an empty spot, in time to do something about it. I built it, no signup.
>
> [planner link]

If the mod is fine with the paid report too, add section 1's second line, Tuesday to Thursday.

## 4. X: the post to pin

> Paste your fantasy roster. See every week a bye leaves you with an empty starting spot, through
> your title game.
>
> Free, no signup. Link in the reply.

First reply:

> [planner link]

## 5. X: the free report, Tuesday morning to Thursday afternoon

> Paste your fantasy roster and get a free lineup report on it. Every slot decided, every close
> call explained. One per person, no card.
>
> Link in the reply.

First reply:

> Get a free report on your own roster: [free report link]

## 6. X: Wednesday, from this week's real report

`content/this-week.md` is rewritten every Wednesday from the live sample. Use those posts. They're
the real report, and they fit a post. Each one says how long it's good for. Each link already
carries its own tag (like `x-w09-closest`), so `make stats` counts it with no `make link`. To see
one on the dashboard's post list too, log its tag, `make link TAG=x-w09-closest WHERE="X"`, and
post the draft's own link. In a week the site doesn't link this week's sample page, the replies
link the home page instead, and the file says why.

## 7. A commissioner, once the League Pass is open

> Running a league? The League Pass gives every manager their own lineup report every Wednesday
> through the title game. $34.99 a month for the league, and it stops on its own.
>
> [link to the League Pass page]
