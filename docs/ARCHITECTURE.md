# Processing model and limitations

## Stages

1. `deduplicate.lambda_handler` reads the incoming CSV and merges it with the existing clean CSV by `Fecha`. New records replace old values on matching dates. Dates are sorted before writing.
2. `weekly.lambda_handler` assigns a record to the Monday of its week and, when it is not a Monday, to the following Monday, weighted by `7 - weekday` and `weekday`. It writes the same result to two S3 buckets.
3. `monthly.lambda_handler` groups weekly rows by their start-date year/month. It computes mean temperature, maximum weekly temperature and maximum supplied deviation. Maximum-temperature difference is calculated against the previous available month, which may not be the previous calendar month.
4. `alerts.lambda_handler` reads weekly values and persistent state. A deviation greater than `0.5` publishes once for that ISO year/week in sequential processing. Falling below the threshold does not reset the sent flag.
5. Flask reads the monthly CSV from S3 for each metric request. There is no application cache or database.

## Schemas

Daily/weekly input: `Fecha,Medias,Desviaciones`, with `Fecha` formatted as `YYYY/MM/DD`.

Monthly output: `anio,mes,temperatura_media,temperatura_max,desviacion_maxima,diff_temperatura`.

Alert state: `week_id,deviation_last_seen,alert_sent`.

## Important assumptions

- Weekly aggregation retains the original coursework weighting rule. It is not an ordinary mean of daily readings, and the interpretation depends on what period each input record represents.
- Averaging supplied deviations does not calculate a pooled standard deviation.
- The academic source contains unfinished cross-month weighting. This edition retains start-month assignment and documents it explicitly.
- Each handler currently processes only `Records[0]`. Multi-record events need explicit iteration in a future revision.
- Read/modify/write operations on CSVs are not transactional. Concurrent updates may lose data; SNS delivery followed by a failed state save may cause a repeated notification on retry. The tests cover sequential replay only.
- Monthly incremental input replaces the metrics for months it contains. It is not a partial-row accumulation mechanism; the normal pipeline sends a complete weekly snapshot.
- The template covers the network and build host only. The rest of the deployment is described in the original report and must be configured separately.
- The example ALB design uses HTTP, and the API has no authentication. Public production use would require a separate design review.
