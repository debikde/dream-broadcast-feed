# Content Factory

Локальная фабрика контента

## Что умеет
- отправлять промпты в локальный Automatic1111 (если он запущен на машине и использует CUDA)
- импортировать любые свои картинки вручную
- отбирать generated/manual -> selected
- одним действием собирать готовый content pack
- автоматически формировать `publish/manifest.json` и ZIP-пак в `publish/packs/`

## Установка
```bash
pip install -r requirements.txt
python main.py
```
## Где лежит готовое
- `publish/manifest.json`
- `publish/packs/pack_*.zip`

## Как подключить CUDA-генерацию
- установи и запусти локальный Automatic1111
- проверь, что его API доступен на `http://127.0.0.1:7860`
