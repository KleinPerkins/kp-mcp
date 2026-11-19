# google-kit capabilities index

Intent → capability card resolver.

> **Prerequisite:** authenticate before calling any op — see [QUICKSTART.md](QUICKSTART.md).
> Error triage: [docs/dev/TRIAGE.md](../../docs/dev/TRIAGE.md).

| Operation | Posture | Card |
|-----------|---------|------|
| `calendar.create` | write | [card](cards/calendar.create.md) |
| `calendar.delete` | destructive | [card](cards/calendar.delete.md) |
| `calendar.freebusy` | read | [card](cards/calendar.freebusy.md) |
| `calendar.list` | read | [card](cards/calendar.list.md) |
| `calendar.update` | write | [card](cards/calendar.update.md) |
| `calendar.watch` | write | [card](cards/calendar.watch.md) |
| `docs.apply_styles` | write | [card](cards/docs.apply_styles.md) |
| `docs.batch_update` | write | [card](cards/docs.batch_update.md) |
| `docs.extract_styles` | read | [card](cards/docs.extract_styles.md) |
| `docs.from_markdown` | write | [card](cards/docs.from_markdown.md) |
| `docs.styles_add` | read | [card](cards/docs.styles_add.md) |
| `docs.styles_apply` | write | [card](cards/docs.styles_apply.md) |
| `docs.styles_doctor` | read | [card](cards/docs.styles_doctor.md) |
| `docs.styles_remove` | read | [card](cards/docs.styles_remove.md) |
| `docs.styles_repair` | read | [card](cards/docs.styles_repair.md) |
| `docs.styles_set_default` | read | [card](cards/docs.styles_set_default.md) |
| `docs.styles_update` | read | [card](cards/docs.styles_update.md) |
| `docs.styles_view` | read | [card](cards/docs.styles_view.md) |
| `drive.changes` | read | [card](cards/drive.changes.md) |
| `drive.changes_watch` | write | [card](cards/drive.changes_watch.md) |
| `drive.comments` | write | [card](cards/drive.comments.md) |
| `drive.copy` | write | [card](cards/drive.copy.md) |
| `drive.create` | write | [card](cards/drive.create.md) |
| `drive.fetch` | read | [card](cards/drive.fetch.md) |
| `drive.permissions` | write | [card](cards/drive.permissions.md) |
| `drive.revisions` | read | [card](cards/drive.revisions.md) |
| `drive.search` | read | [card](cards/drive.search.md) |
| `drive.trash` | destructive | [card](cards/drive.trash.md) |
| `drive.update` | write | [card](cards/drive.update.md) |
| `drive.upload` | write | [card](cards/drive.upload.md) |
| `drive_activity.query` | read | [card](cards/drive_activity.query.md) |
| `events.delete` | destructive | [card](cards/events.delete.md) |
| `events.list` | read | [card](cards/events.list.md) |
| `events.patch` | write | [card](cards/events.patch.md) |
| `events.subscribe` | write | [card](cards/events.subscribe.md) |
| `forms.add_item` | write | [card](cards/forms.add_item.md) |
| `forms.create` | write | [card](cards/forms.create.md) |
| `forms.get` | read | [card](cards/forms.get.md) |
| `forms.get_response` | read | [card](cards/forms.get_response.md) |
| `forms.list_responses` | read | [card](cards/forms.list_responses.md) |
| `forms.publish` | write | [card](cards/forms.publish.md) |
| `forms.update` | write | [card](cards/forms.update.md) |
| `forms.watches` | write | [card](cards/forms.watches.md) |
| `gmail.attachments` | read | [card](cards/gmail.attachments.md) |
| `gmail.batch_modify` | write | [card](cards/gmail.batch_modify.md) |
| `gmail.draft` | write | [card](cards/gmail.draft.md) |
| `gmail.get` | read | [card](cards/gmail.get.md) |
| `gmail.history` | read | [card](cards/gmail.history.md) |
| `gmail.labels` | read | [card](cards/gmail.labels.md) |
| `gmail.list` | read | [card](cards/gmail.list.md) |
| `gmail.manage_labels` | write | [card](cards/gmail.manage_labels.md) |
| `gmail.modify` | write | [card](cards/gmail.modify.md) |
| `gmail.profile` | read | [card](cards/gmail.profile.md) |
| `gmail.search` | read | [card](cards/gmail.search.md) |
| `gmail.send` | write | [card](cards/gmail.send.md) |
| `gmail.thread_get` | read | [card](cards/gmail.thread_get.md) |
| `gmail.threads` | read | [card](cards/gmail.threads.md) |
| `gmail.watch` | write | [card](cards/gmail.watch.md) |
| `keep.create` | write | [card](cards/keep.create.md) |
| `keep.delete` | destructive | [card](cards/keep.delete.md) |
| `keep.get` | read | [card](cards/keep.get.md) |
| `keep.list` | read | [card](cards/keep.list.md) |
| `people.batch_get` | read | [card](cards/people.batch_get.md) |
| `people.connections` | read | [card](cards/people.connections.md) |
| `people.get` | read | [card](cards/people.get.md) |
| `people.list_directory` | read | [card](cards/people.list_directory.md) |
| `people.search_directory` | read | [card](cards/people.search_directory.md) |
| `recipes.build_styled` | write | [card](cards/recipes.build_styled.md) |
| `recipes.build_then_share` | write | [card](cards/recipes.build_then_share.md) |
| `recipes.hydrate_then_refine` | write | [card](cards/recipes.hydrate_then_refine.md) |
| `recipes.template_merge` | write | [card](cards/recipes.template_merge.md) |
| `script.create` | write | [card](cards/script.create.md) |
| `script.create_deployment` | write | [card](cards/script.create_deployment.md) |
| `script.create_version` | write | [card](cards/script.create_version.md) |
| `script.delete_deployment` | destructive | [card](cards/script.delete_deployment.md) |
| `script.deployments` | read | [card](cards/script.deployments.md) |
| `script.get_content` | read | [card](cards/script.get_content.md) |
| `script.get_deployment` | read | [card](cards/script.get_deployment.md) |
| `script.get_version` | read | [card](cards/script.get_version.md) |
| `script.metrics` | read | [card](cards/script.metrics.md) |
| `script.run` | write | [card](cards/script.run.md) |
| `script.update_content` | write | [card](cards/script.update_content.md) |
| `script.update_deployment` | write | [card](cards/script.update_deployment.md) |
| `script.versions` | read | [card](cards/script.versions.md) |
| `sheets.add_sheet` | write | [card](cards/sheets.add_sheet.md) |
| `sheets.append` | write | [card](cards/sheets.append.md) |
| `sheets.chart` | write | [card](cards/sheets.chart.md) |
| `sheets.conditional_format` | write | [card](cards/sheets.conditional_format.md) |
| `sheets.create` | write | [card](cards/sheets.create.md) |
| `sheets.info` | read | [card](cards/sheets.info.md) |
| `sheets.metadata` | write | [card](cards/sheets.metadata.md) |
| `sheets.pivot` | write | [card](cards/sheets.pivot.md) |
| `sheets.read` | read | [card](cards/sheets.read.md) |
| `sheets.write` | write | [card](cards/sheets.write.md) |
| `slides.add_image` | write | [card](cards/slides.add_image.md) |
| `slides.add_slide` | write | [card](cards/slides.add_slide.md) |
| `slides.create` | write | [card](cards/slides.create.md) |
| `slides.get` | read | [card](cards/slides.get.md) |
| `slides.thumbnail` | read | [card](cards/slides.thumbnail.md) |
| `slides.update_text` | write | [card](cards/slides.update_text.md) |
| `tasks.complete` | write | [card](cards/tasks.complete.md) |
| `tasks.create` | write | [card](cards/tasks.create.md) |
| `tasks.delete` | destructive | [card](cards/tasks.delete.md) |
| `tasks.list` | read | [card](cards/tasks.list.md) |
| `tasks.list_lists` | read | [card](cards/tasks.list_lists.md) |
| `tasks.update` | write | [card](cards/tasks.update.md) |

## Routed capabilities

Native host connectors can consume canonical document style data through the
[bounded native Doc style provider route](../../docs/runbooks/native-doc-style-provider.md).
This separate interface does not replace CLI/MCP registration or qualify the
full operation index.

These are not separate ops — they are URL-routing behaviours within existing ops.

| Intent | Handled by | Notes |
|--------|------------|-------|
| Google Sites (`https://sites.google.com/…`) | `drive.fetch` | Pass the Sites URL as `url_or_id`. Requires Chrome + browser_cookie3 + Playwright — see [Google Sites prerequisites](QUICKSTART.md#google-sites-prerequisites). |
