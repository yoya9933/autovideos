# VideoTurn Tech Stack

## ?瑁??啣?

雿平蝟餌絞嚗indows / PowerShell
銝餉?隤?嚗ython
銝餌?撘?MoneyPrinterTurbo portable bundle
?瑁??亙嚗?撅?`run_daily_auto_publish.bat`
???亙嚗install_scheduler.bat` ?Ｙ? `VideoTurn\AutoPublish_Morning` ??`VideoTurn\AutoPublish_Afternoon`

## ?頝臬?

| 憿? | 頝臬? |
| --- | --- |
| App repo | `MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo` |
| Portable Python | `MoneyPrinterTurbo-Portable-Windows-1.2.6\lib\python\python.exe` |
| 銝餅?蝔?| `MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo\auto_publish_youtube.py` |
| RSS/Prompt | `app\services\rss_ingest.py` |
| LLM | `app\services\llm.py` |
| YouTube | `app\services\youtube_upload.py`, `app\services\youtube_publisher.py` |
| 憭像??| `app\services\platform_publish.py`, `instagram_reels_publish.py`, `facebook_reels_publish.py` |
| Job evidence | `storage\auto_publish\jobs\*.json` |
| Publish status | `storage\auto_publish\publish_status\*.json` |
| Logs | `storage\auto_publish\logs\*.log` |

## 撽??孵?

?芸?雿輻 portable Python????unittest ??`storage\auto_publish\logs\daily_YYYY-MM-DD.log` 甈???瑼仃?????葫閰西?甇?? log ?梁 sink ??憿?銝?隤文?箸平?葫閰血仃??
## Secrets

`.env` ?◤ `app\config\config.py` 頛嚗?憓??豢?閬? `config.toml`???瑟??? `.env` ?蝘??銝靘?嚗config.toml` 靽???撖身摰?蝛箏潦?