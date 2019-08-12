|configVar|redis key|redis type|value example|meaning|Remark|
|---------|---|---|---------|-------|------|
|TARGET_DOMAIN|-|-|test/beta/prod|one of top level names under which instl admin functions can be done|-|
|TARGET_MAJOR_VERSION|-|-|V10/V11/Common|one of the specific division inside TARGET_DOMAIN|-|
|TARGET_REPO_REV|-|-|523|specific repository revision|-|
|RUNNING_WHERE|-|-|porter/stout|machine where admin instl is wating for triggers|-|
|TARGET_REFERENCE|-|-|test:Common:236|combination of domain+major_version+repo_rev|-|
|SVN_COMMIT_TRIGGER_REDIS_KEY|wv:$(WHO):trigger:svn:commit|LIST|test:V10:256 |a value is lpush'ed to this key for each svn submit|WHO is replaced by the name of whoever runs the code responding to the trigger, e.g. porter/stout/...|
|ACTIVATE_REPO_REV_TRIGGER_REDIS_KEY|wv:$(WHO):trigger:activate:repo-rev|LIST|prod:V11:17|a value is lpush'ed to this key for each repo-rev activation|
|UPLOADED_REPO_REVS_REDIS_KEY| wv:$(TARGET_DOMAIN):$(TARGET_MAJOR_VERSION):uploaded_repo_revs|LIST|1,2,3|List of uploaded repo-revs for domain/version|DOMAIN= dev/test/beta/prod<br/> VERSION=V9/V10/V11/Common|
|UPLOAD_IN_PROGRESS_REDIS_KEY|wv:$(RUNNING_WHERE):upload_in_progress|STR|$(TRAGET_REFERENCE) or None|$(TRAGET_REFERENCE) when upload is in progress or None when not|-|
|ACTIVATE_IN_PROGRESS_REDIS_KEY|wv:$(RUNNING_WHERE):activate_in_progress|STR|123 or None|$(TRAGET_REFERENCE) when activation is in progress or None when not|-|
|ACTIVATED_REPO_REV_REDIS_KEY|wv:$(TARGET_DOMAIN):$(TARGET_MAJOR_VERSION):activated_repo_rev|STR|123|repo-rev currntly active for domain/version|-|
