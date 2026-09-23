# 01: Единое поле исхода Opponent

**What to build:** модель возвращает обычную реплику или ровно один тип исхода через discriminated
`resolution`, а публичный снимок поединка сохраняет текущую форму.

Status: ready-for-agent

- [ ] Внутренний model contract содержит одно nullable `resolution` с обязательным `kind`.
- [ ] Normal, agreement, partial и deferred преобразуются в прежний `SessionState`.
- [ ] Guard, Validator, приватность и bounded retry продолжают применяться до фиксации хода.
- [ ] Model gateway тест подтверждает discriminator в переданной JSON Schema.
- [ ] Публичный OpenAPI не изменился, полный набор тестов проходит.
- [ ] Три живых eval-прогона зафиксированы в комментариях.

## Comments

- 2026-09-23: Создано по результатам wire-диагностики: два последовательных ответа второго хода
  содержали одновременно `agreement` и `decision` и были корректно отклонены.
