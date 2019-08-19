|configVar|redis key|redis type|value example|meaning|Remark|
|---------|---|---|---------|-------|------|
|TARGET_DOMAIN|-|-|test/beta/prod|one of top level names under which instl admin functions can be done|-|
|TARGET_MAJOR_VERSION|-|-|V10/V11/Common|one of the specific division inside TARGET_DOMAIN|-|
|TARGET_REPO_REV|-|-|523|specific repository revision|-|
|RUNNING_WHERE|-|-|porter/stout|machine where admin instl is wating for triggers|-|
|TARGET_REFERENCE|-|-|test:Common:236|combination of domain+major_version+repo_rev|-|
|HEARTBEAT_COUNTER_REDIS_KEY|wv:$(RUNNING_WHERE):heartbeat|INT|123|periodic heartbeat|-|
| | | | | | |
|UPLOAD_REPO_REV_WAITING_LIST_REDIS_KEY|wv:$(RUNNING_WHERE):upload_repo_rev:waiting_list|LIST|test:V10:256 |a value is lpush'ed to this key for each svn submit|WHO is replaced by the name of whoever runs the code responding to the trigger, e.g. porter/stout/...|
|UPLOAD_REPO_REV_IN_PROGRESS_REDIS_KEY|wv:$(RUNNING_WHERE):upload_repo_rev:in_progress|STR|$(TRAGET_REFERENCE) or None|$(TRAGET_REFERENCE) when upload is in progress or None when not|-|
|UPLOAD_REPO_REV_DONE_LIST_REDIS_KEY|wv:$(RUNNING_WHERE):upload_repo_rev:done_list|LIST|1,2,3|List of uploaded repo-revs for domain/version|DOMAIN= dev/test/beta/prod<br/> VERSION=V9/V10/V11/Common|
| | | | | | |
|ACTIVATE_REPO_REV_WAITING_LIST_REDIS_KEY|wv:$(RUNNING_WHERE):activate_repo_rev:waiting_list|LIST|prod:V11:17|a value is lpush'ed to this key for each repo-rev activation|
|ACTIVATE_REPO_REV_IN_PROGRESS_REDIS_KEY|wv:$(RUNNING_WHERE):activate_repo_rev:in_progress|STR|123 or None|$(TRAGET_REFERENCE) when activation is in progress or None when not|-|
|ACTIVATE_REPO_REV_DONE_LIST_REDIS_KEY|wv:$(RUNNING_WHERE):activate_repo_rev:done_list|LIST|1,2,3|all repo-revs activated for domain/version|-|
|ACTIVATE_REPO_REV_CURRENT_REDIS_KEY|wv:$(TARGET_DOMAIN):$(TARGET_MAJOR_VERSION):active_repo_rev|STR|123|repo-rev currntly active for domain/version|-|
|UPLOAD_REPO_REV_LAST_UPLOADED_REDIS_KEY|wv:$(TARGET_DOMAIN):$(TARGET_MAJOR_VERSION):last_uploaded_repo_rev|STR|123|last successful uploaded rep-rev for domain/version|-|
