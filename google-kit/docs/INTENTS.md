# google-kit intent manifest

Natural-language → operation triggers behind `google-kit help <intent>` and the
MCP `help` tool. Generated from the registry — do not edit by hand; run
`uv run python -m google_kit.aliases_gen`. Curate phrases in
`core/manifest._CURATED_ALIASES` / `OpSpec.aliases`; service synonyms in
`_SERVICE_TRIGGERS`.

## Common intents (curated)

Hand-curated phrases for the workhorse operations — the operator-signed
discovery surface. Every other op stays discoverable via its name tokens and
service synonyms (see the trigger table below).

| Intent | Operation | CLI |
|--------|-----------|-----|
| add a collaborator | `drive.permissions` | `google-kit drive permissions` |
| add a question to a form | `forms.add_item` | `google-kit forms add-item` |
| add a question | `forms.add_item` | `google-kit forms add-item` |
| add a todo | `tasks.create` | `google-kit tasks create` |
| add an item to a survey | `forms.add_item` | `google-kit forms add-item` |
| archive a message | `gmail.modify` | `google-kit gmail modify` |
| book time | `calendar.create` | `google-kit calendar create` |
| check availability | `calendar.freebusy` | `google-kit calendar freebusy` |
| check my inbox | `gmail.list` | `google-kit gmail list` |
| compose and send mail | `gmail.send` | `google-kit gmail send` |
| create a doc from markdown | `docs.from_markdown` | `google-kit docs from-markdown` |
| create a document in drive | `drive.create` | `google-kit drive create` |
| create a form | `forms.create` | `google-kit forms create` |
| create a task | `tasks.create` | `google-kit tasks create` |
| create an event | `calendar.create` | `google-kit calendar create` |
| delete a file | `drive.trash` | `google-kit drive trash` |
| download a file | `drive.fetch` | `google-kit drive fetch` |
| draft an email | `gmail.draft` | `google-kit gmail draft` |
| duplicate a file | `drive.copy` | `google-kit drive copy` |
| email someone | `gmail.send` | `google-kit gmail send` |
| file change history | `drive_activity.query` | `google-kit drive_activity query` |
| find a coworker | `people.search_directory` | `google-kit people search-directory` |
| find a file | `drive.search` | `google-kit drive search` |
| find an email | `gmail.search` | `google-kit gmail search` |
| find free time | `calendar.freebusy` | `google-kit calendar freebusy` |
| get cell values | `sheets.read` | `google-kit sheets read` |
| get file contents | `drive.fetch` | `google-kit drive fetch` |
| get someone's profile | `people.get` | `google-kit people get` |
| grant access | `drive.permissions` | `google-kit drive permissions` |
| label an email | `gmail.modify` | `google-kit gmail modify` |
| list emails | `gmail.list` | `google-kit gmail list` |
| list events | `calendar.list` | `google-kit calendar list` |
| locate a document | `drive.search` | `google-kit drive search` |
| look up a contact | `people.get` | `google-kit people get` |
| make a copy | `drive.copy` | `google-kit drive copy` |
| make a new file | `drive.create` | `google-kit drive create` |
| make a presentation | `slides.create` | `google-kit slides create` |
| make a spreadsheet | `sheets.create` | `google-kit sheets create` |
| make a survey | `forms.create` | `google-kit forms create` |
| mark as read | `gmail.modify` | `google-kit gmail modify` |
| move to trash | `drive.trash` | `google-kit drive trash` |
| my schedule | `calendar.list` | `google-kit calendar list` |
| new sheet | `sheets.create` | `google-kit sheets create` |
| new slide deck | `slides.create` | `google-kit slides create` |
| open a doc | `drive.fetch` | `google-kit drive fetch` |
| publish markdown as a google doc | `docs.from_markdown` | `google-kit docs from-markdown` |
| read a document | `drive.fetch` | `google-kit drive fetch` |
| read spreadsheet data | `sheets.read` | `google-kit sheets read` |
| recent mail | `gmail.list` | `google-kit gmail list` |
| remind me to | `tasks.create` | `google-kit tasks create` |
| save a draft | `gmail.draft` | `google-kit gmail draft` |
| schedule a meeting | `calendar.create` | `google-kit calendar create` |
| search drive | `drive.search` | `google-kit drive search` |
| search mail | `gmail.search` | `google-kit gmail search` |
| search the directory | `people.search_directory` | `google-kit people search-directory` |
| send an email | `gmail.send` | `google-kit gmail send` |
| share a file | `drive.permissions` | `google-kit drive permissions` |
| update cells | `sheets.write` | `google-kit sheets write` |
| what's on my calendar | `calendar.list` | `google-kit calendar list` |
| when am i free | `calendar.freebusy` | `google-kit calendar freebusy` |
| who changed a file | `drive_activity.query` | `google-kit drive_activity query` |
| write to a sheet | `sheets.write` | `google-kit sheets write` |

## Operation triggers

All match tokens per op (name + capability + curated/explicit aliases [strong] and service synonyms [weak]). The resolver ranks strong-token and exact-phrase hits above shared service synonyms.

| Operation | CLI | Plane | Triggers |
|-----------|-----|-------|----------|
| `calendar.create` | `google-kit calendar create` | — | appointment, availability, book, calendar, create, event, events, invite, meeting, schedule, time |
| `calendar.delete` | `google-kit calendar delete` | — | appointment, availability, calendar, cancel, delete, event, events, invite, meeting, remove, schedule |
| `calendar.freebusy` | `google-kit calendar freebusy` | — | am, appointment, availability, calendar, check, event, events, find, free, freebusy, invite, meeting, schedule, time, when |
| `calendar.list` | `google-kit calendar list` | — | appointment, availability, calendar, event, events, invite, list, meeting, schedule, show, what |
| `calendar.update` | `google-kit calendar update` | — | appointment, availability, calendar, change, event, events, invite, meeting, reschedule, schedule, time, update |
| `calendar.watch` | `google-kit calendar watch` | eventing | appointment, availability, calendar, event, eventing, events, invite, meeting, schedule, watch |
| `docs.apply_styles` | `google-kit docs apply-styles` | content | apply, doc, docs, document, google, make, profile, restyle, style, styles, theme, use, word, writeup |
| `docs.batch_update` | `google-kit docs batch-update` | content | apply, batch, changes, doc, docs, document, edit, google, modify, update, word, writeup |
| `docs.extract_styles` | `google-kit docs extract-styles` | content | copy, doc, docs, document, extract, google, profile, save, style, styles, theme, word, writeup |
| `docs.from_markdown` | `google-kit docs from-markdown` | content | as, create, doc, docs, document, from, google, markdown, publish, word, writeup |
| `docs.styles_add` | `google-kit docs styles-add` | content | add, create, doc, docs, document, manage, profile, save, style, styles, word, writeup |
| `docs.styles_apply` | `google-kit docs styles-apply` | content | apply, doc, docs, document, profile, restyle, style, styles, word, writeup |
| `docs.styles_doctor` | `google-kit docs styles-doctor` | content | doc, docs, doctor, document, fix, manage, profile, profiles, repair, style, styles, word, writeup |
| `docs.styles_remove` | `google-kit docs styles-remove` | content | delete, doc, docs, document, manage, profile, remove, style, styles, word, writeup |
| `docs.styles_repair` | `google-kit docs styles-repair` | content | doc, docs, doctor, document, manage, profile, profiles, repair, style, styles, word, writeup |
| `docs.styles_set_default` | `google-kit docs styles-set-default` | content | default, doc, docs, document, make, manage, profile, set, style, styles, word, writeup |
| `docs.styles_update` | `google-kit docs styles-update` | content | change, doc, docs, document, edit, manage, profile, style, styles, update, word, writeup |
| `docs.styles_view` | `google-kit docs styles-view` | content | doc, docs, document, list, manage, profile, profiles, show, style, styles, view, word, writeup |
| `drive.changes` | `google-kit drive changes` | container | changes, document, download, drive, file, files, folder, folders, permission, read, share, storage, upload |
| `drive.changes_watch` | `google-kit drive changes-watch` | eventing | changes, document, download, drive, eventing, file, files, folder, folders, permission, share, storage, upload, watch |
| `drive.comments` | `google-kit drive comments` | container | comment, comments, create, document, download, drive, file, files, folder, folders, permission, share, storage, upload |
| `drive.copy` | `google-kit drive copy` | container | clone, copy, document, download, drive, duplicate, file, files, folder, folders, make, permission, share, storage, upload |
| `drive.create` | `google-kit drive create` | container | blank, create, document, download, drive, file, files, folder, folders, make, new, permission, share, storage, upload |
| `drive.fetch` | `google-kit drive fetch` | container | contents, doc, document, download, drive, fetch, file, files, folder, folders, get, open, permission, read, share, storage, upload |
| `drive.permissions` | `google-kit drive permissions` | container | access, add, collaborator, document, download, drive, file, files, folder, folders, grant, permission, permissions, share, storage, upload, user |
| `drive.revisions` | `google-kit drive revisions` | container | document, download, drive, file, files, folder, folders, permission, read, revision, revisions, share, storage, upload |
| `drive.search` | `google-kit drive search` | container | document, download, drive, file, files, find, folder, folders, locate, look, permission, search, share, storage, upload, where |
| `drive.trash` | `google-kit drive trash` | container | delete, document, download, drive, file, files, folder, folders, move, permission, remove, share, storage, trash, upload |
| `drive.update` | `google-kit drive update` | container | change, document, download, drive, file, files, folder, folders, metadata, name, permission, rename, share, storage, update, upload |
| `drive.upload` | `google-kit drive upload` | container | document, download, drive, file, files, folder, folders, permission, share, storage, upload |
| `drive_activity.query` | `google-kit drive_activity query` | history | activity, audit, change, changed, changes, drive, file, history, query, read, when, who |
| `events.delete` | `google-kit events delete` | eventing | delete, eventing, events, notification, push, subscribe, subscription, subscriptions, watch, webhook |
| `events.list` | `google-kit events list` | eventing | eventing, events, list, notification, push, subscribe, subscription, subscriptions, watch, webhook |
| `events.patch` | `google-kit events patch` | eventing | eventing, events, notification, patch, push, subscribe, subscription, subscriptions, watch, webhook |
| `events.subscribe` | `google-kit events subscribe` | eventing | eventing, events, notification, push, subscribe, subscription, subscriptions, watch, webhook |
| `forms.add_item` | `google-kit forms add-item` | content | add, field, form, forms, item, poll, question, questionnaire, quiz, survey |
| `forms.create` | `google-kit forms create` | content | create, form, forms, make, new, poll, questionnaire, quiz, survey |
| `forms.get` | `google-kit forms get` | content | form, forms, get, poll, questionnaire, quiz, survey |
| `forms.get_response` | `google-kit forms get-response` | content | form, forms, get, poll, questionnaire, quiz, response, survey |
| `forms.list_responses` | `google-kit forms list-responses` | content | form, forms, get, list, poll, questionnaire, quiz, responses, survey |
| `forms.publish` | `google-kit forms publish` | content | form, forms, poll, publish, questionnaire, quiz, survey |
| `forms.update` | `google-kit forms update` | content | form, forms, poll, questionnaire, quiz, survey, update |
| `forms.watches` | `google-kit forms watches` | eventing | eventing, form, forms, poll, questionnaire, quiz, survey, watch, watches |
| `gmail.attachments` | `google-kit gmail attachments` | messaging | attachment, attachments, email, gmail, inbox, mail, message, messages, read, reply, thread |
| `gmail.batch_modify` | `google-kit gmail batch-modify` | messaging | batch, email, gmail, inbox, mail, message, messages, modify, reply, thread |
| `gmail.draft` | `google-kit gmail draft` | messaging | compose, draft, email, gmail, inbox, mail, message, messages, reply, save, thread |
| `gmail.get` | `google-kit gmail get` | messaging | email, get, gmail, inbox, mail, message, messages, reply, thread |
| `gmail.history` | `google-kit gmail history` | messaging | email, gmail, history, inbox, mail, message, messages, read, reply, thread |
| `gmail.labels` | `google-kit gmail labels` | messaging | email, gmail, inbox, labels, mail, message, messages, reply, thread |
| `gmail.list` | `google-kit gmail list` | messaging | check, email, emails, gmail, inbox, list, mail, message, messages, recent, reply, thread, what |
| `gmail.manage_labels` | `google-kit gmail manage-labels` | messaging | email, gmail, inbox, labels, mail, manage, message, messages, reply, thread |
| `gmail.modify` | `google-kit gmail modify` | messaging | archive, as, email, gmail, inbox, label, mail, mark, message, messages, modify, read, reply, thread |
| `gmail.profile` | `google-kit gmail profile` | messaging | email, gmail, inbox, mail, message, messages, profile, reply, thread |
| `gmail.search` | `google-kit gmail search` | messaging | email, find, gmail, inbox, look, mail, message, messages, reply, search, thread |
| `gmail.send` | `google-kit gmail send` | messaging | compose, email, gmail, inbox, mail, message, messages, reply, send, someone, thread |
| `gmail.thread_get` | `google-kit gmail thread-get` | messaging | email, get, gmail, inbox, mail, message, messages, read, reply, thread |
| `gmail.threads` | `google-kit gmail threads` | messaging | email, gmail, inbox, mail, message, messages, read, reply, thread, threads |
| `gmail.watch` | `google-kit gmail watch` | eventing | email, eventing, gmail, inbox, mail, message, messages, reply, thread, watch |
| `keep.create` | `google-kit keep create` | — | checklist, create, keep, memo, note, notes |
| `keep.delete` | `google-kit keep delete` | — | checklist, delete, keep, memo, note, notes |
| `keep.get` | `google-kit keep get` | — | checklist, get, keep, memo, note, notes |
| `keep.list` | `google-kit keep list` | — | checklist, keep, list, memo, note, notes |
| `people.batch_get` | `google-kit people batch-get` | identity | batch, colleague, contact, contacts, coworker, directory, get, identity, people, person, profile, read |
| `people.connections` | `google-kit people connections` | identity | colleague, connections, contact, contacts, coworker, directory, identity, people, person, profile, read |
| `people.get` | `google-kit people get` | identity | colleague, contact, contacts, coworker, directory, get, identity, look, people, person, profile, read, someone, up |
| `people.list_directory` | `google-kit people list-directory` | identity | colleague, contact, contacts, coworker, directory, identity, list, people, person, profile, search |
| `people.search_directory` | `google-kit people search-directory` | identity | colleague, contact, contacts, coworker, directory, find, identity, people, person, profile, search |
| `recipes.build_styled` | `google-kit recipes build-styled` | content | build, compose, create, doc, draft, markdown, multi-step, pipeline, recipe, recipes, style, styled, workflow |
| `recipes.build_then_share` | `google-kit recipes build-then-share` | content | and, build, compose, create, doc, draft, markdown, multi-step, pipeline, publish, recipe, recipes, share, then, workflow |
| `recipes.hydrate_then_refine` | `google-kit recipes hydrate-then-refine` | content | and, compose, context, doc, document, edit, hydrate, multi-step, pipeline, read, recipe, recipes, refine, then, update, workflow |
| `recipes.template_merge` | `google-kit recipes template-merge` | content | compose, copy, doc, fields, fill, mail, merge, multi-step, pipeline, placeholders, recipe, recipes, replace, template, workflow |
| `script.create` | `google-kit script create` | automation | apps-script, automation, create, function, macro, script |
| `script.create_deployment` | `google-kit script create-deployment` | automation | apps-script, automation, create, deployment, function, macro, script |
| `script.create_version` | `google-kit script create-version` | automation | apps-script, automation, create, function, macro, script, version |
| `script.delete_deployment` | `google-kit script delete-deployment` | automation | apps-script, automation, delete, deployment, function, macro, script |
| `script.deployments` | `google-kit script deployments` | automation | apps-script, automation, deployments, function, macro, script |
| `script.get_content` | `google-kit script get-content` | automation | apps-script, automation, content, function, get, macro, script |
| `script.get_deployment` | `google-kit script get-deployment` | automation | apps-script, automation, deployment, function, get, macro, script |
| `script.get_version` | `google-kit script get-version` | automation | apps-script, automation, function, get, macro, script, version |
| `script.metrics` | `google-kit script metrics` | automation | apps-script, automation, function, macro, metrics, script |
| `script.run` | `google-kit script run` | automation | apps-script, automation, function, macro, run, script |
| `script.update_content` | `google-kit script update-content` | automation | apps-script, automation, content, function, macro, script, update |
| `script.update_deployment` | `google-kit script update-deployment` | automation | apps-script, automation, deployment, function, macro, script, update |
| `script.versions` | `google-kit script versions` | automation | apps-script, automation, function, macro, script, versions |
| `sheets.add_sheet` | `google-kit sheets add-sheet` | content | add, cell, cells, column, excel, row, sheet, sheets, spreadsheet, table |
| `sheets.append` | `google-kit sheets append` | content | add, append, cell, cells, column, excel, row, sheet, sheets, spreadsheet, table |
| `sheets.chart` | `google-kit sheets chart` | content | cell, cells, chart, column, excel, row, sheet, sheets, spreadsheet, table |
| `sheets.conditional_format` | `google-kit sheets conditional-format` | content | cell, cells, column, conditional, excel, format, row, sheet, sheets, spreadsheet, table |
| `sheets.create` | `google-kit sheets create` | content | cell, cells, column, create, excel, make, new, row, sheet, sheets, spreadsheet, table |
| `sheets.info` | `google-kit sheets info` | content | cell, cells, column, excel, info, row, sheet, sheets, spreadsheet, table |
| `sheets.metadata` | `google-kit sheets metadata` | content | cell, cells, column, developer, excel, metadata, row, sheet, sheets, spreadsheet, table |
| `sheets.pivot` | `google-kit sheets pivot` | content | cell, cells, column, excel, pivot, row, sheet, sheets, spreadsheet, table |
| `sheets.read` | `google-kit sheets read` | content | cell, cells, column, data, excel, get, read, row, sheet, sheets, spreadsheet, table, values |
| `sheets.write` | `google-kit sheets write` | content | cell, cells, column, data, excel, put, row, set, sheet, sheets, spreadsheet, table, update, values, write |
| `slides.add_image` | `google-kit slides add-image` | content | add, deck, image, insert, photo, picture, powerpoint, presentation, slide, slides |
| `slides.add_slide` | `google-kit slides add-slide` | content | add, deck, powerpoint, presentation, slide, slides |
| `slides.create` | `google-kit slides create` | content | create, deck, make, new, powerpoint, presentation, slide, slides |
| `slides.get` | `google-kit slides get` | content | deck, get, powerpoint, presentation, slide, slides |
| `slides.thumbnail` | `google-kit slides thumbnail` | content | deck, getthumbnail, pages, powerpoint, presentation, slide, slides, thumbnail |
| `slides.update_text` | `google-kit slides update-text` | content | deck, powerpoint, presentation, slide, slides, text, update |
| `tasks.complete` | `google-kit tasks complete` | — | checklist, complete, reminder, task, tasks, to-do, todo |
| `tasks.create` | `google-kit tasks create` | — | add, checklist, create, remind, reminder, task, tasks, to-do, todo |
| `tasks.delete` | `google-kit tasks delete` | — | checklist, delete, reminder, task, tasks, to-do, todo |
| `tasks.list` | `google-kit tasks list` | — | checklist, list, reminder, task, tasks, to-do, todo |
| `tasks.list_lists` | `google-kit tasks list-lists` | — | checklist, list, lists, reminder, task, tasks, to-do, todo |
| `tasks.update` | `google-kit tasks update` | — | checklist, reminder, task, tasks, to-do, todo, update |
