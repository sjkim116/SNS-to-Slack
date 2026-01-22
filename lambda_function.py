"""
AWS Lambda: CloudWatch Alarm Slack Notifier (임시 브랜치)
- CloudWatch 단일/다중 지표 알람을 Slack에 간결하게 전송
- SNS 메시지 파싱 오류를 별도로 처리하여 알림 실패 방지
- 다중지표는 인스턴스 이름 캐싱 및 실측값 출력
- 모든 시간은 KST(또는 리전 타임존)로 출력
- 이벤트 히스토리와 대시보드/경보 바로가기 제공
- 다중 채널 푸시 지원
- boto3 클라이언트 재사용으로 효율성 개선

작성자: Nuricloud (개선: 2026-01-22)
버전: 2026-01-22-client-reuse
"""

import boto3
import json
import os
import urllib3
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import boto3.session

instance_name_cache = {}

def get_instance_name(ec2_client, instance_id):
    if instance_id in instance_name_cache:
        return instance_name_cache[instance_id]
    reservations = ec2_client.describe_instances(InstanceIds=[instance_id])['Reservations']
    for reservation in reservations:
        for instance in reservation['Instances']:
            for tag in instance.get('Tags', []):
                if tag['Key'] == 'Name':
                    name = tag['Value']
                    instance_name_cache[instance_id] = name
                    return name
    instance_name_cache[instance_id] = instance_id
    return instance_id

def get_alarm_history(cloudwatch, alarm_name, tz):
    history = cloudwatch.describe_alarm_history(
        AlarmName=alarm_name,
        HistoryItemType='StateUpdate',
        MaxRecords=3,
        ScanBy='TimestampDescending'
    )
    items = history.get('AlarmHistoryItems', [])
    return [
        f"- {h['Timestamp'].astimezone(tz).strftime('%Y-%m-%dT%H:%M:%S')} {tz.key} : `{h['HistorySummary']}`"
        for h in items
    ]

def get_latest_metric_value(cloudwatch, namespace, metric_name, dimensions, stat, period, start_time, end_time):
    response = cloudwatch.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=[stat]
    )
    datapoints = response.get('Datapoints', [])
    if datapoints:
        latest = sorted(datapoints, key=lambda x: x['Timestamp'], reverse=True)[0]
        return latest.get(stat)
    return None

def lambda_handler(event, context):
    http = urllib3.PoolManager()
    detail_lines = []
    header_text = "*[ALARM]* Slack 메시지 기본값"
    
    session = boto3.session.Session()
    region = os.environ.get('AWS_REGION') or session.region_name or 'ap-northeast-2'
    tz = ZoneInfo({
        'ap-northeast-2': 'Asia/Seoul',
        'us-east-1': 'America/New_York',
        'us-west-1': 'America/Los_Angeles',
        'eu-west-1': 'Europe/Dublin',
        'ap-southeast-1': 'Asia/Singapore',
        'ap-southeast-2': 'Australia/Sydney'
    }.get(region, 'UTC'))

    cloudwatch = boto3.client('cloudwatch')
    ec2 = boto3.client('ec2')
    webhook_urls = os.getenv('SLACK_WEBHOOK_URL', '').split(',')
    webhook_urls = [url.strip() for url in webhook_urls if url.strip()]
    if not webhook_urls:
        raise ValueError("환경 변수 'SLACK_WEBHOOK_URL'이 하나 이상 설정되어 있어야 합니다.")

    try:
        sns_message = json.loads(event['Records'][0]['Sns']['Message'])
        alarm_name = sns_message.get('AlarmName', '(알 수 없음)')
        new_state = sns_message.get('NewStateValue', 'UNKNOWN')
        alarm_description = sns_message.get('AlarmDescription', '')
        trigger = sns_message.get('Trigger', {})
        metrics = trigger.get('Metrics', [])
        is_single_metric = not metrics and 'MetricName' in trigger

        datapoint_match = re.search(r"\[(\d+\.\d+)", sns_message.get("NewStateReason", ""))
        datapoint_value = f"{round(float(datapoint_match.group(1)), 1)}" if datapoint_match else "?"
        unit = trigger.get('Unit') or "%"
        header_text = f"*[{new_state}]* `{datapoint_value} {unit}` | `{alarm_name}`"

        try:
            state_change_time = datetime.strptime(sns_message['StateChangeTime'], "%Y-%m-%dT%H:%M:%S.%f%z")
        except Exception:
            state_change_time = datetime.now(tz)

        if is_single_metric:
            metric_name = trigger.get('MetricName', 'Unknown')
            namespace = trigger.get('Namespace', 'Unknown')
            dims = trigger.get('Dimensions', [])
            dim_str = ', '.join(f"{d['name']}={d['value']}" for d in dims)
            stat = trigger.get('Statistic', '')
            period = trigger.get('Period', '')
            reason = sns_message.get('NewStateReason', '')
            timestamp = state_change_time.astimezone(tz).strftime('%Y-%m-%dT%H:%M:%S') + f" {tz.key}"
            detail_lines += [
                f"`{namespace}/{metric_name}` / `{dim_str}` / {datapoint_value} {unit} ({stat}/{period}s)",
                f"사유: {reason}",
                f"시각: {timestamp}"
            ]
            if alarm_description:
                detail_lines.append(f"설명: {alarm_description}")
        else:
            start_time = state_change_time - timedelta(minutes=5)
            end_time = state_change_time
            for metric in metrics:
                if 'MetricStat' in metric:
                    stat_data = metric['MetricStat']
                    metric_name = stat_data['Metric']['MetricName']
                    namespace = stat_data['Metric']['Namespace']
                    dims = stat_data['Metric']['Dimensions']
                    instance_id = next((d.get('Value') or d.get('value') for d in dims if (d.get('Name') or d.get('name')) == 'InstanceId'), None)
                    instance_name = get_instance_name(ec2, instance_id) if instance_id else "-"
                    stat = stat_data['Stat']
                    period = stat_data['Period']
                    unit = stat_data.get('Unit', '') or '%'
                    value = get_latest_metric_value(cloudwatch, namespace, metric_name, [
                        {'Name': d.get('Name') or d.get('name'), 'Value': d.get('Value') or d.get('value')}
                        for d in dims
                    ], stat, period, start_time, end_time)
                    value_str = f"{round(value, 1)}" if isinstance(value, (int, float)) else "?"
                    detail_lines.append(f"{value_str} {unit} / `{namespace}/{metric_name}` / `{instance_name}` ({stat}/{period}s)")
            reason = sns_message.get('NewStateReason', '')
            timestamp = state_change_time.astimezone(tz).strftime('%Y-%m-%dT%H:%M:%S') + f" {tz.key}"
            detail_lines += [f"사유: {reason}", f"시각: {timestamp}"]
            if alarm_description:
                detail_lines.append(f"설명: {alarm_description}")

        recent_events = get_alarm_history(cloudwatch, alarm_name, tz)
        if recent_events:
            detail_lines.append("*최근 알람 이벤트:*")
            detail_lines.extend(recent_events)

        detail_lines.append(
            "<https://ap-northeast-2.console.aws.amazon.com/cloudwatch/home?region=ap-northeast-2#alarmsV2:|경보 바로가기> | "
            "<https://ap-northeast-2.console.aws.amazon.com/cloudwatch/home?region=ap-northeast-2#dashboards/|대시보드 바로가기>"
        )

    except Exception as e:
        header_text = f"*[ERROR]* Slack 알림 처리 실패"
        detail_lines = [f":warning: SNS 메시지 파싱 예외 발생: `{e}`"]

    slack_message = {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "\n".join(detail_lines)}]}
        ]
    }

    for url in webhook_urls:
        try:
            http.request(
                'POST',
                url,
                body=json.dumps(slack_message).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            print(f"[ERROR] Slack 전송 실패: {e}")

    return {'statusCode': 200, 'body': 'Slack 전송 로직 완료됨'}
