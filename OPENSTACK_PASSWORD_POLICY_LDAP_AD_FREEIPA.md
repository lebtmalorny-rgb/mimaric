# OpenStack Epoxy 2025.1: парольная политика с MS AD или FreeIPA

Дата проверки источников: 17 сентября 2026 года.

## 1. Краткий вывод и выбранная схема

Документ описывает прямой вход: **Horizon → Keystone → LDAP bind в MS AD / FreeIPA**. Человеческие пользователи должны иметь пароль от 8 символов с алфавитом от 70 символов, обязательно менять установленный администратором пароль и блокироваться после 4 ошибок с ручной либо автоматической разблокировкой.

**Схема подтверждена пользователем: через LDAP входят только люди с ролями `admin`, `member` и другими; OpenStack service users находятся в SQL Keystone и через LDAP не аутентифицируются. Сервисные записи полностью освобождаются от человеческих требований, включая длину и сложность.**

| Учётная запись | Где проверяется пароль | Где назначаются права |
|---|---|---|
| Человек, в том числе администратор | MS AD или FreeIPA через LDAP backend домена | Роли `admin`, `member`, `reader` и другие в Keystone |
| Технический пользователь Nova, Neutron и других сервисов | SQL backend Keystone | Сервисные назначения ролей в Keystone |
| LDAP bind identity Keystone | Каталог, только для технического поиска пользователей/групп | LDAP ACL чтения; это не service user Nova/Neutron |

Backend выбирается доменом учётной записи. Роль определяет авторизацию и сама по себе не переключает LDAP/SQL.

Парольную политику людей обеспечивает каталог. Keystone LDAP backend работает в режиме чтения и не выполняет смену LDAP-пароля. Для обязательной смены перед доступом к OpenStack:

- **MS AD:** признак обязательной смены + портал, умеющий менять временный/истёкший пароль AD; ниже приведён вариант на уже развёрнутом Keycloak;
- **FreeIPA:** обязательная смена после административного сброса + встроенный Web UI + запрет LDAP grace-входов;
- обычный LDAP bind и выдача нового password token Keystone до смены должны отклоняться.

Патч Keystone для этой схемы не нужен, если в локальном SQL-домене остаются только выделенные технические записи. Если там также есть человеческий администратор или break-glass пользователь, для него требуется политика из [руководства SQL](OPENSTACK_PASSWORD_POLICY_LOCAL_SQL.md), включая [подготовленные патчи Keystone/Kolla](https://github.com/lebtmalorny-rgb/mimaric/blob/60bbc29354ee852cf70bed835235344a205f3468/README.md) для исключения сервисов. Не объявлять личную административную запись сервисной ради обхода политики.

Основание: [Keystone LDAP integration](https://docs.openstack.org/keystone/2025.1/admin/configuration.html#integrate-identity-with-ldap), [код LDAP authenticate/change_password](https://docs.openstack.org/keystone/2025.1/_modules/keystone/identity/backends/ldap/core.html).

## 2. Что подготовить и где настраивать

| Место | Что требуется |
|---|---|
| MS AD / FreeIPA | Группа людей, парольная политика, блокировка, сброс и разблокировка |
| Каталог | Отдельная служебная bind identity; только необходимые права чтения для Keystone |
| Портал смены | HTTPS, доверие к CA каталога, поддержка временных/истёкших паролей |
| Deploy-узел Kolla | `/etc/kolla/config/keystone.conf` и `keystone/domains/keystone.<DOMAIN_NAME>.conf` |
| Deploy-узел Kolla | `/etc/kolla/config/horizon/_9999-custom-settings.py` |
| Deploy-узел Kolla | CA в `/etc/kolla/certificates/ca/`, включение доставки CA |
| Keystone API | Домен LDAP, проектные роли пользователей или групп |

Имена `corp.example.org`, `dc1.corp.example.org`, `ipa1.corp.example.org`, `CORP_AD`, `CORP_IPA`, DN и UUID в примерах заменяются на реальные. Это руководство настройки существующего каталога, Kolla и, при выборе AD-портала, существующего Keycloak; установка ОС и развёртывание этих продуктов с нуля не входят в него.

До изменений зафиксировать версии, топологию каталогов, список DC/IPA replicas, существующие ID mappings и текущие политики. Не менять `user_id_attribute` работающего домена: это может изменить отображение LDAP-пользователей в Keystone и нарушить назначения ролей.

Все команды применения ниже предназначены для оператора; при подготовке документа они не выполнялись.

## 3. MS AD: политика людей

### 3.1. Отдельная FGPP

На Windows-узле с модулем ActiveDirectory и делегированными правами подготовить глобальную группу безопасности `OpenStack-Human-Users`. Добавлять только реальные человеческие записи, включая администраторов виртуализации.

Пример создания отдельного Password Settings Object; если объект уже существует, сначала прочитать его и применять согласованные изменения через `Set-ADFineGrainedPasswordPolicy`:

```powershell
Import-Module ActiveDirectory
New-ADGroup -Name 'OpenStack-Human-Users' -GroupScope Global `
    -GroupCategory Security -Path 'OU=Groups,DC=corp,DC=example,DC=org'
Add-ADGroupMember -Identity 'OpenStack-Human-Users' -Members <HUMAN_SAMACCOUNTNAME>
$domainPolicy = Get-ADDefaultDomainPasswordPolicy
$humanPolicy = @{
    Name = 'OpenStack-Humans'
    Precedence = 20
    ComplexityEnabled = $true
    MinPasswordLength = 8
    MinPasswordAge = [TimeSpan]::Zero
    MaxPasswordAge = $domainPolicy.MaxPasswordAge
    PasswordHistoryCount = 1
    LockoutThreshold = 4
    LockoutDuration = [TimeSpan]::FromMinutes(15)
    LockoutObservationWindow = [TimeSpan]::FromMinutes(15)
    ReversibleEncryptionEnabled = $false
}
New-ADFineGrainedPasswordPolicy @humanPolicy
Add-ADFineGrainedPasswordPolicySubject `
    -Identity 'OpenStack-Humans' -Subjects 'OpenStack-Human-Users'
Get-ADUserResultantPasswordPolicy -Identity <HUMAN_SAMACCOUNTNAME>
```

`MaxPasswordAge` в примере сохраняет доменное значение; исходное требование периодической ротации не задаёт. `Precedence=20` — образец: меньший номер имеет больший приоритет, а индивидуальные назначения PSO также влияют на результат. Проверить результирующую политику каждого класса пользователей.

`LockoutObservationWindow` задаёт окно учёта ошибок; это отдельный параметр от времени блокировки. Если критерий требует накопления любых четырёх ошибок без ограничения по времени, приведённое 15-минутное окно ему не эквивалентно и должно быть отдельно согласовано.

FGPP назначаются пользователям и глобальным группам безопасности. Перенос пользователя в OU сам по себе не назначает ему такую политику. Источники: [Microsoft FGPP](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/get-started/adac/fine-grained-password-policies), [New-ADFineGrainedPasswordPolicy](https://learn.microsoft.com/en-us/powershell/module/activedirectory/new-adfinegrainedpasswordpolicy?view=windowsserver2025-ps).

### 3.2. Первичный пароль и разблокировка

Администратор задаёт пароль интерактивно и требует смену:

```powershell
$initialPassword = Read-Host 'Temporary password' -AsSecureString
Set-ADAccountPassword -Identity <HUMAN_SAMACCOUNTNAME> `
    -Reset -NewPassword $initialPassword
Set-ADUser -Identity <HUMAN_SAMACCOUNTNAME> -ChangePasswordAtLogon $true
Get-ADUser -Identity <HUMAN_SAMACCOUNTNAME> `
    -Properties pwdLastSet,LockedOut,PasswordNeverExpires
```

Не сочетать требование смены с несовместимыми флагами пользовательской записи, например `PasswordNeverExpires=true`. Проверить фактический `pwdLastSet=0`. Перед административной выдачей учётных данных закончить установку признака обязательной смены.

Ручная разблокировка:

```powershell
Unlock-ADAccount -Identity <HUMAN_SAMACCOUNTNAME>
```

Администратору виртуализации делегируются нужные операции AD; роль `admin` в OpenStack не предоставляет их автоматически. При выбранных параметрах автоматическая разблокировка происходит по политике AD. Источники: [Set-ADUser](https://learn.microsoft.com/en-us/powershell/module/activedirectory/set-aduser?view=windowsserver2025-ps), [Unlock-ADAccount](https://learn.microsoft.com/en-us/powershell/module/activedirectory/unlock-adaccount?view=windowsserver2025-ps).

### 3.3. Смена временного пароля: портал Keycloak для AD

Этот вариант использует Keycloak как портал самообслуживания. Переключение Horizon на SSO для него не обязательно: пользователь завершает смену в портале, затем возвращается к текущему LDAP-входу Horizon.

В выделенном realm на уже развёрнутом Keycloak:

| Настройка LDAP User Federation | Значение/действие |
|---|---|
| Vendor | Active Directory |
| Connection URL | `ldaps://dc1.corp.example.org:636`, сертификат проверяется |
| Users DN | Область человеческих пользователей |
| Username LDAP attribute | `sAMAccountName` либо принятый в организации UPN |
| UUID LDAP attribute | `objectGUID` |
| User LDAP filter | Членство в `OpenStack-Human-Users` |
| Edit Mode | `WRITABLE` |
| Bind identity | Отдельная identity портала с минимальными нужными правами; не bind identity Keystone |
| Sync registrations | Выключено, если пользователи создаются администратором AD |
| LDAP mapper | `MSAD User Account Mapper` |

Загрузить доверенные CA в truststore Keycloak штатным способом для его версии. Не отключать проверку сертификата. Проверить permissions записи, TLS и тестовое изменение пароля: переключатель `WRITABLE` сам по себе прав в AD не выдаёт.

Mapper связывает `pwdLastSet=0` с обязательным действием `UPDATE_PASSWORD`. Пользователь открывает `https://sso.example.org/realms/openstack-humans/account/`, проходит форму смены, новый пароль записывается в AD. Realm должен обслуживать только людей; не подключать сюда сервисные identities и не назначать им глобальные required actions.

Проверить, что пароль действительно изменился в AD, `pwdLastSet` обновлён, старый пароль не работает, новый работает в Horizon. Административная учётная запись портала не должна превращать смену в обход AD-политики. Источник: [Keycloak LDAP, edit mode и MSAD mapper](https://www.keycloak.org/docs/latest/server_admin/index.html#_ldap).

Если нужен единый переход Horizon → смена → Horizon, дополнительно настраивается OIDC-федерация. Kolla 2025.1 имеет [поддержку OIDC](https://docs.openstack.org/kolla-ansible/2025.1/reference/shared-services/keystone-guide.html#federated-identity). Это отдельное изменение способа входа: простое включение `WEBSSO_ENABLED` не создаёт IdP, mapping или защищённый процесс смены.

## 4. FreeIPA: политика людей и встроенная смена пароля

### 4.1. Версия и групповая политика

На административном IPA-клиенте:

```bash
ipa --version
ipa help pwpolicy
ipa pwpolicy-add --help
ipa pwpolicy-mod --help
```

Нужна версия с поддержкой `--gracelimit` и исправлениями LDAP grace-проверки. Механизм появился в ветке 4.9.10; последующие исправления присутствуют в 4.9.11/4.10.1. Для дистрибутива проверить backports, а не только номер. Источники: [4.9.10](https://www.freeipa.org/page/Releases/4.9.10), [4.9.11](https://www.freeipa.org/page/Releases/4.9.11).

Пример создания группы и политики; для существующих объектов использовать `group-add-member` / `pwpolicy-mod` после чтения текущих значений:

```bash
kinit <IPA_POLICY_ADMIN>
ipa group-add openstack-human-users --desc='Human OpenStack users'
ipa group-add-member openstack-human-users --users=<HUMAN_LOGIN>
ipa pwpolicy-add openstack-human-users \
  --priority=20 \
  --minlength=8 --minclasses=3 \
  --minlife=0 --history=1 \
  --maxfail=4 --failinterval=900 --lockouttime=900 \
  --gracelimit=0
ipa pwpolicy-show --user=<HUMAN_LOGIN> --all
```

`minclasses=3` — дополнительное правило сложности; само число классов не означает алфавит из 70 символов. Состав разрешённых символов проверяется отдельно, как описано в разделе 8. Параметры максимального срока жизни пароля и прочие поля результирующей политики проверить явно: требования задачи не определяют их.

Применяется одна результирующая политика, а не объединение всех групповых правил. Меньший номер priority выше; проверить пересечение групп и индивидуальный результат. Окно `failinterval=900` допускает сброс ошибок после интервала — не трактовать его как накопление четырёх ошибок за любое время. [Red Hat IdM: парольные политики](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/managing_idm_users_groups_hosts_and_access_control_rules/defining-idm-password-policies_managing-users-groups-hosts), [ansible-freeipa: значения параметров](https://www.freeipa.org/ansible-freeipa.github.io/documentation/plugins/pwpolicy.html).

### 4.2. Почему обязательно `gracelimit=0`

В FreeIPA административно установленный пароль требует смены, однако исторически истечение пароля не запрещало обычный LDAP bind. Значение grace limit `-1` отключает ограничение, положительное число разрешает дополнительные bind после истечения. Для обязательной смены **до доступа к OpenStack** требуется `0` у человеческой политики.

Нельзя ограничиться успешным тестом `kinit`: Keystone использует LDAP bind. Проверить именно этот путь и отсутствие нового Keystone token до смены. Описание механизма: [FreeIPA LDAP grace period](https://github.com/freeipa/freeipa/blob/ipa-4-12/doc/designs/ldap_grace_period.md).

### 4.3. Первичный пароль, Web UI и разблокировка

Администратор создаёт пользователя, назначает группу, затем устанавливает временный пароль:

```bash
ipa user-add <HUMAN_LOGIN> --first=<FIRST_NAME> --last=<LAST_NAME>
ipa group-add-member openstack-human-users --users=<HUMAN_LOGIN>
ipa passwd <HUMAN_LOGIN>
```

Пароль вводится в приглашении. При административном сбросе пользователь должен сменить его. Использовать IPA API/CLI, а не обходные LDAP-записи от Directory Manager. Временный пароль также следует выдавать согласно принятому правилу: административный reset в некоторых путях не выполняет те же проверки качества, что самосмена. [FreeIPA: правила смены](https://www.freeipa.org/page/Administrators_Guide).

Если требуется автоматический запрет короткого/недопустимого временного пароля и на административном reset, процесс выдачи паролей должен отдельно выполнять такую проверку. Одна IPA-групповая политика не доказывает её наличие. Для исключения обхода этот процесс должен быть единственным делегированным способом сброса для операторов; прямой привилегированный reset остаётся административной возможностью каталога. Такой интерфейс выдачи в рамках документа не реализован.

Пользователь открывает `https://ipa1.corp.example.org/ipa/ui/`, выбирает вход по имени и паролю и вводит временный пароль. Web UI предлагает смену истёкшего пароля. После смены пользователь входит в Horizon с новым паролем. Этот путь нужно проверить вместе с `gracelimit=0`; открытая Kerberos-сессия браузера не должна подменять тест временного пароля. [FreeIPA Web UI](https://www.freeipa.org/page/Web_UI).

Проверка состояния и ручная разблокировка:

```bash
ipa user-status <HUMAN_LOGIN>
ipa user-unlock <HUMAN_LOGIN>
```

Делегировать оператору виртуализации права именно на нужные IPA-операции. Не выдавать полные права администратора каталога только ради разблокировки.

### 4.4. Технический LDAP-поиск

Для поиска пользователей Keystone использует отдельную read-only bind identity. Она не является учётной записью OpenStack-сервиса и не включается в `openstack-human-users`. Не использовать здесь персонального пользователя или Directory Manager. FreeIPA описывает [system account для LDAP-поиска](https://www.freeipa.org/page/HowTo/LDAP); способ его создания, ACL и срок действия выбрать для установленной версии.

Пароли Nova, Neutron и других OpenStack services в этой схеме не попадают в FreeIPA, поэтому создавать для них IPA-группы и парольные политики не требуется.

### 4.5. Реплики и общий порог 4

IPA Lockout обрабатывает LDAP bind, но нельзя считать, что счётчик автоматически общий для всех реплик. Документ FreeIPA о replicated lockout описывает проект изменения, а не доказательство реализации в вашем релизе. [Описание проблемы](https://www.freeipa.org/page/V4/Replicated_lockout), [LDAP lockout plugin](https://github.com/freeipa/freeipa/blob/ipa-4-12/daemons/ipa-slapi-plugins/ipa-lockout/ipa_lockout.c).

Пример ниже использует один IPA endpoint для аутентификации. Для строгого порога в этом варианте все Keystone workers должны попадать на один и тот же IPA-сервер; это ограничивает отказоустойчивость. Добавление второго URL, балансировки или failover требует отдельной проверки переноса состояния. При локальных счётчиках переключение реплики даёт дополнительные попытки и не выполняет строгий общий предел 4.

Если одновременно необходимы HA и общий порог 4, потребуется подтверждённый механизм общего учёта/блокировки либо другой процесс аутентификации с общим счётчиком и исключённым обходом. Просто поставить Keycloak перед несколькими IPA replicas и сохранить прямой LDAP-вход недостаточно. Это отдельное решение, не готовая настройка данного руководства.

## 5. Keystone через Kolla-Ansible

### 5.1. Доверие к CA

На deploy-узле разместить CA каталога, например `/etc/kolla/certificates/ca/directory-ca.crt`. В `/etc/kolla/globals.yml`:

```yaml
kolla_copy_ca_into_containers: "yes"
```

Kolla доставляет дополнительные CA в контейнеры. В LDAP-конфиге указать действующий bundle внутри образа:

- Debian/Ubuntu: `/etc/ssl/certs/ca-certificates.crt`;
- Rocky/RHEL: `/etc/pki/tls/certs/ca-bundle.crt`.

Не путать системный CA deploy-узла с CA внутри Keystone. Если локальная поставка получает сертификаты из Vault, использовать её действующий способ доставки CA вместо параллельного файлового механизма. [Kolla TLS](https://docs.openstack.org/kolla-ansible/2025.1/admin/tls.html#adding-ca-certificates-to-the-service-containers), локальная роль доставки сертификатов (`kolla-ansible-pvs_1.0.0/ansible/roles/service-cert-copy/tasks/main.yml` в исходном архиве Kolla).

### 5.2. Общая конфигурация

Файл `/etc/kolla/config/keystone.conf`:

```ini
[identity]
driver = sql
domain_specific_drivers_enabled = true
domain_config_dir = /etc/keystone/domains

[security_compliance]
password_regex =
change_password_upon_first_use = false
unique_last_password_count = 0
minimum_password_age = 0
```

Этот фрагмент предназначен для схемы «все люди в LDAP; SQL только для технических identities». Общий SQL regex не нужен и не должен затрагивать service users. Из ранее введённых overrides удалить SQL `lockout_failure_attempts`, `lockout_duration`, `password_expires_days`, `disable_user_account_days_inactive`, если они применялись к этому SQL-контингенту; проверить итоговые значения, включая host-specific overrides. Нельзя задавать `lockout_failure_attempts=0`: у этой опции Keystone минимальное значение 1, отключение обеспечивается отсутствием настройки.

Если в SQL есть люди, этот фрагмент не применять как общую политику: использовать сочетание LDAP-настроек с разделением пользователей из [SQL-руководства](OPENSTACK_PASSWORD_POLICY_LOCAL_SQL.md).

Создать LDAP-домен через административную OpenStack-сессию, если он ещё не существует:

```bash
openstack domain create CORP_AD
```

Для FreeIPA вместо него использовать `CORP_IPA`. Если подключаются оба каталога, создать оба домена и отдельные файлы. Имя в имени файла должно совпадать с именем Keystone-домена.

### 5.3. Пример домена MS AD

Файл `/etc/kolla/config/keystone/domains/keystone.CORP_AD.conf`:

```ini
[identity]
driver = ldap

[ldap]
url = ldaps://dc1.corp.example.org:636
user = CN=svc-keystone-reader,OU=ServiceAccounts,DC=corp,DC=example,DC=org
password = REPLACE_WITH_BIND_SECRET
suffix = DC=corp,DC=example,DC=org
query_scope = sub

user_tree_dn = OU=People,DC=corp,DC=example,DC=org
user_objectclass = person
user_id_attribute = objectGUID
user_name_attribute = sAMAccountName
user_mail_attribute = mail
user_filter = (memberOf=CN=OpenStack-Human-Users,OU=Groups,DC=corp,DC=example,DC=org)
user_enabled_attribute = userAccountControl
user_enabled_mask = 2
user_enabled_default = 512
user_enabled_invert = false

group_tree_dn = OU=Groups,DC=corp,DC=example,DC=org
group_objectclass = group
group_id_attribute = objectGUID
group_name_attribute = cn
group_member_attribute = member

use_tls = false
tls_req_cert = demand
tls_cacertfile = /etc/ssl/certs/ca-certificates.crt
use_auth_pool = false
```

`use_tls=false` здесь означает отсутствие STARTTLS поверх уже защищённого `ldaps://`, а не отключение TLS. Для Rocky заменить bundle. Групповой фильтр предполагает прямое членство; вложенные группы требуют отдельно проверенного AD-фильтра. Маска enabled проверяет отключение записи, а парольный lockout проверяет сам AD при bind.

### 5.4. Пример домена FreeIPA

Файл `/etc/kolla/config/keystone/domains/keystone.CORP_IPA.conf`:

```ini
[identity]
driver = ldap

[ldap]
url = ldaps://ipa1.corp.example.org:636
user = uid=keystone-reader,cn=sysaccounts,cn=etc,dc=corp,dc=example,dc=org
password = REPLACE_WITH_BIND_SECRET
suffix = dc=corp,dc=example,dc=org
query_scope = sub

user_tree_dn = cn=users,cn=accounts,dc=corp,dc=example,dc=org
user_objectclass = person
user_id_attribute = uid
user_name_attribute = uid
user_mail_attribute = mail
user_filter = (memberOf=cn=openstack-human-users,cn=groups,cn=accounts,dc=corp,dc=example,dc=org)
user_enabled_attribute = nsAccountLock
user_enabled_invert = true
user_enabled_default = false

group_tree_dn = cn=groups,cn=accounts,dc=corp,dc=example,dc=org
group_objectclass = groupOfNames
group_id_attribute = cn
group_name_attribute = cn
group_member_attribute = member

use_tls = false
tls_req_cert = demand
tls_cacertfile = /etc/ssl/certs/ca-certificates.crt
use_auth_pool = false
```

Bind DN должен соответствовать реально созданной системной записи и её ACL. `uid`/`cn` в примере подходят для нового домена с неизменяемыми именами; для существующего домена сохранить текущие ID-атрибуты. `use_auth_pool=false` исключает повторное использование аутентифицированных пользовательских LDAP-соединений в проверяемом сценарии блокировки.

Оба фрагмента — шаблоны нового подключения, не указание перезаписать действующую LDAP-интеграцию. Проверить атрибуты read-only запросом `ldapsearch` до применения. Пароль bind identity хранить в защищённом источнике конфигурации; не включать заполненный файл в Git или отчёт. [Keystone domain/LDAP configuration](https://docs.openstack.org/keystone/2025.1/admin/configuration.html#domain-specific-configuration).

## 6. Horizon и назначения ролей

Файл `/etc/kolla/config/horizon/_9999-custom-settings.py`:

```python
OPENSTACK_KEYSTONE_MULTIDOMAIN_SUPPORT = True
OPENSTACK_KEYSTONE_DEFAULT_DOMAIN = 'CORP_AD'
OPENSTACK_KEYSTONE_BACKEND.update({
    'name': 'ldap',
    'can_edit_user': False,
    'can_edit_group': False,
})
HORIZON_CONFIG['password_validator'] = {
    'regex': '.*',
    'help_text': 'Пароль управляется во внешнем каталоге.',
}
```

Для FreeIPA выбрать `CORP_IPA`. Переключение домена в интерфейсе не запрещает API-доступ к другим доменам. `can_edit_user/group=False` — подсказка интерфейсу, а не механизм безопасности; она действует глобально и также скрывает управление SQL-записями в этих формах. Сервисные SQL identities в этой схеме обслуживаются через административную автоматизацию/API.

Не включать `ALLOW_USERS_CHANGE_EXPIRED_PASSWORD=True` как способ записи в LDAP: этот параметр не добавляет такую возможность Keystone. Адрес портала должен быть доступен до успешного входа и передаваться пользователю вместе с инструкцией. Ссылка только в меню уже открытого Horizon недостаточна. Добавление кнопки на страницу входа выполняется отдельно через поддерживаемую тему/расширение, а не вымышленный параметр `PASSWORD_RESET_URL`.

Проверить обнаружение пользователей и назначить роли по существующей модели RBAC, например для тестового проекта:

```bash
openstack user list --domain CORP_AD
openstack role add --user <LDAP_USER_ID> --project <PROJECT_ID> member
```

Для FreeIPA заменить имя домена. Не создавать SQL-копию человека с тем же именем для обхода ошибок LDAP. Источник UI-настроек: [Horizon settings](https://docs.openstack.org/horizon/2025.1/configuration/settings.html#openstack-keystone-backend).

## 7. Порядок применения и проверки подключения

1. Подготовить человеческую политику в каталоге и проверить результирующие значения. OpenStack service users не переносить в LDAP; технические bind identities не включать в человеческую группу.
2. Подготовить и проверить портал смены на отдельном пользователе, включая просроченный временный пароль.
3. Подготовить CA, bind identity, доменный конфиг, Horizon override и назначения ролей.
4. Проверить, что технические SQL-пользователи действительно исключены из человеческой политики; отдельно разобрать локальных людей.
5. На deploy-узле в согласованное окно выполнить:

```bash
kolla-ansible -i /path/to/inventory prechecks --tags keystone,horizon
kolla-ansible -i /path/to/inventory reconfigure --tags keystone,horizon
```

6. На каждом Keystone-узле проверить итоговый доменный файл `/etc/keystone/domains/keystone.<DOMAIN>.conf` внутри контейнера, доступность CA bundle и одинаковый endpoint аутентификации. Вывод пароля bind-записи не сохранять.
7. Проверить LDAPS из той же сетевой зоны и с тем же CA, откуда работает Keystone. Например на диагностическом узле с LDAP-клиентом:

```bash
LDAPTLS_CACERT=/path/to/directory-ca.pem ldapwhoami \
  -x -H ldaps://dc1.corp.example.org:636 \
  -D 'CN=test-user,OU=People,DC=corp,DC=example,DC=org' -W
```

Для FreeIPA использовать его endpoint и DN тестового пользователя. Пароль вводить через `-W`, не через аргумент `-w`. Успех с deploy-узла не доказывает доверие CA и доступность LDAP внутри контейнера.

Доставку доменных файлов и override-пути подтверждают локальные задачи Keystone (`kolla-ansible-pvs_1.0.0/ansible/roles/keystone/tasks/config.yml` в исходном архиве Kolla), шаблон Keystone (`kolla-ansible-pvs_1.0.0/ansible/roles/keystone/templates/keystone.conf.j2` в исходном архиве Kolla) и задачи Horizon (`kolla-ansible-pvs_1.0.0/ansible/roles/horizon/tasks/config.yml` в исходном архиве Kolla).

## 8. Алфавит пароля и критерии приёмки

Минимальная длина и мощность алфавита — разные требования. Алфавит `A–Z`, `a–z`, `0–9` и 32 печатных знака ASCII без пробела содержит 94 символа. Политика AD `ComplexityEnabled` и IPA `minclasses` описывают классы символов, но не являются настройкой «алфавит=70».

Для приёмки зафиксировать допустимый набор и проверить его прохождение через портал/клиент, каталог и LDAP-вход. Проверки выполнять с паролями, удовлетворяющими остальным ограничениям: не проверять один знак как самостоятельный пароль. Если требуется ограничить допустимый набор строго определёнными символами или ввести нестандартные правила состава, нужен соответствующий password filter/quality plugin каталога с областью применения к человеческим пользователям. Валидация только в Horizon не закрывает прямой API.

Набор проверок на отдельных тестовых identities:

| Сценарий | Ожидаемый результат |
|---|---|
| Самосмена человеческого пароля на 7 символов | Отказ каталога |
| Самосмена на 8+ допустимых символов | Успех |
| Новый/административно сброшенный человеческий пароль до смены | LDAP bind для доступа к OpenStack и новый password token Keystone неуспешны |
| FreeIPA при `gracelimit=0` | Нет даже первого grace-входа в Keystone |
| Смена временного пароля через AD-портал / IPA Web UI | Успех, затем новый пароль работает в Horizon |
| Отказ/закрытие формы смены | Доступ к OpenStack не выдан |
| Три ошибки, затем правильный пароль | Вход возможен; проверить сброс счётчика |
| Четыре ошибки в согласованном окне, затем правильный пароль | Новый вход блокируется |
| Ручная разблокировка и отдельный тест окончания таймера | Новый вход работает |
| Локальный SQL service user: тестовый пароль вне человеческой сложности | Разрешён в Keystone; LDAP-политика к этой записи не применяется |
| Тестовая SQL-сервисная запись после четырёх ошибок | Человеческая блокировка каталога не действует; глобальная SQL-блокировка не включена |
| Сервис после административной ротации | Не требуется интерактивная первая смена |
| Человеческие входы через Horizon, CLI и direct LDAP | Нет обхода другим способом входа; тест сервиса проводится отдельно через SQL Keystone |
| Попытки через все Keystone workers и DC/IPA replicas, включая failover | Проверен фактический общий порог и состояние блокировки |

Не доказывать соответствие порога только значением `4` в конфигурации. Нужны реальные backend-запросы, учёт повторов клиента, конкурентных входов и состояния реплик. При расхождении между политикой и фактическим числом попыток внедрение не принимать до устранения причины.

Проверки не должны блокировать рабочие service users. Сохранять время, ID/логин, endpoint, код ответа и состояние счётчика без паролей и токенов. Не включать debug-логирование секретных тел запросов.

Блокировка новых парольных входов в каталоге не гарантирует немедленный отзыв всех ранее выданных Keystone-токенов или application credentials. Если требуется прекращение уже открытого доступа, определить отдельный процесс отзыва и проверить его.

## 9. Откат и границы подтверждения

Вернуть сохранённые исходные политики/членство и overrides, применить изменения ко всем затронутым узлам. Не удалять LDAP-домен и не менять ID-атрибуты как способ отката паролей: это другая операция с последствиями для идентичностей и RBAC.

Снятие настройки обязательной смены не означает восстановления прежнего пароля. Уже изменённый пароль остаётся изменённым; истёкшие/заблокированные тестовые записи восстановить штатными средствами каталога.

Проверены официальные источники OpenStack, Microsoft, FreeIPA/Red Hat, выбранные upstream-файлы и локальные роли Kolla-Ansible. Конкретные версии AD/IPA/Keycloak, действующие ACL, multi-DC поведение, контейнеры и пользовательские сценарии на стенде не проверялись. Фрагменты требуют подстановки DN, имён, CA и секретов. Портал AD и строгий общий lockout в HA должны быть подтверждены отдельно; документация не является протоколом испытаний.
