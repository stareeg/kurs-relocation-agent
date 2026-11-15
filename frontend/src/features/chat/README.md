# Чаты (`chat`)

домен бэкенда: `core/domains/assistant`

Шаг U-0/U-1: главный экран «Агент» — один свободный чат (`AgentChat`, персист в localStorage).
Переписка с HR (`VacancyConversationPane` + `VacancyChatHeader`) живёт во вкладке «Чат с HR»
дровера вакансии в разделе «Вакансии». Ручное добавление вакансии — `features/jobs/
AddVacancyDialog` в тулбаре «Вакансий». «Контексты» (notes-панели) убраны; notes API остался
на бэкенде (RAG).
