# Teacher Telegram demo

This checkout now contains a small vertical slice for the hackathon:

- nanobot remains the agent runtime and Telegram channel.
- `demo/teacher_data.json` is synthetic class data.
- `simo/teacher_demo.py` provides deterministic overview, missing-work, report,
  and message-draft operations.
- `simo/teacher_tools.py` exposes those operations as nanobot tools.
- `nanobot/skills/teacher-assistant/SKILL.md` teaches the agent when to use them.

## Run locally without Telegram

From `nanobot-base`:

```powershell
python scripts\run_teacher_demo.py
python -m pytest --confcutdir=tests\simo tests\simo\test_teacher_demo.py -q
```

## Connect the existing Telegram bot

Install the checkout into the same environment used by the bot so the
`nanobot.tools` entry-point and bundled skill are available:

```powershell
uv sync --extra dev
nanobot plugins enable telegram
nanobot channels status
nanobot gateway
```

Keep Telegram in pairing-only mode for the demo. After pairing, ask:

- `Give me an overview of class-7a`
- `Which students have missing work in class-7a?`
- `Prepare the weekly report for class-7a`
- `Draft a supportive message for student-003 in class-7a`

The Telegram command menu also provides teacher shortcuts:

- `/overview class-7a`
- `/missing class-7a`
- `/report class-7a`
- `/draft student-003 in class-7a`

These shortcuts are translated into the same agent prompts as the natural
language examples, so they use the same permissions and tools.

The message tool only creates a draft. It does not send anything.

The current tools use synthetic JSON, not Google Classroom or Excel. The next
integration step is to replace the store behind these same tool contracts with
read-only Google Classroom/Sheets connectors and add approval-gated export
actions.

## Email drafts and sending

Email uses nanobot's existing SMTP-backed Email channel. Configure that
channel with a verified sender, SMTP credentials, `consentGranted: true`, and
the required channel enablement before testing delivery.

Ask Telegram for an email draft with a recipient:

```text
Draft an email to parent@example.com for student-003 in class-7a about the missing work
```

Simo will show the recipient, subject, and body and label it **Draft only**.
Review the complete draft, then send a new message containing the exact phrase:

```text
SEND EMAIL
```

The send tool also receives the reviewed recipient, subject, and body and
routes the message through nanobot's Email channel. Without the exact approval
phrase in the current teacher message, the email is blocked. A queued email is
not proof of delivery; inspect the Email channel logs or mailbox for delivery.
