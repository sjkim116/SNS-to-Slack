# AWS CloudWatch Alarm Slack Notifier

AWS CloudWatch에서 발생하는 경보를 지정된 Slack 채널로 전송하는 Lambda 함수입니다. 단일 지표 및 다중 지표(Composite) 경보를 모두 지원하며, 가독성 높은 형식으로 메시지를 가공하여 전달합니다.

## 주요 기능

-   **CloudWatch 경보 실시간 알림**: `ALARM`, `OK`, `INSUFFICIENT_DATA` 상태 변경을 Slack으로 즉시 전송합니다.
-   **다중/단일 지표 지원**: 단일 지표 경보와 여러 지표를 조합한 다중 지표 경보를 모두 파싱하여 명확하게 표시합니다.
-   **가독성 높은 메시지**:
    -   경보의 핵심 원인(실측값)을 메시지 제목에 표시합니다.
    -   EC2 인스턴스 ID를 실제 `Name` 태그 값으로 변환하여 보여줍니다. (인스턴스 이름은 캐싱하여 불필요한 API 호출을 줄입니다.)
    -   경보 발생 시각을 한국 시간(KST) 또는 리전별 타임존으로 자동 변환하여 표시합니다.
-   **상세 정보 제공**:
    -   최근 3개의 경보 상태 변경 이력을 함께 제공하여 컨텍스트 파악을 돕습니다.
    -   AWS 콘솔의 경보 및 대시보드 페이지로 바로 이동할 수 있는 링크를 포함합니다.
-   **다중 채널 지원**: 하나의 Lambda 함수로 여러 Slack 채널에 동시에 알림을 보낼 수 있습니다.
-   **안정적인 파싱**: SNS 메시지 구조가 예상과 다르더라도, Lambda 함수 실행이 중단되지 않고 오류 메시지를 Slack으로 보내도록 설계되었습니다.

## Slack 알림 예시

### 단일 지표 경보 (ALARM 상태)
!단일 지표 경보 예시

### 다중 지표 경보 (OK 상태)
!다중 지표 경보 예시

### 오류 발생 시
!오류 메시지 예시


## 구성 및 설치 방법

### 1. Slack Webhook URL 발급

1.  알림을 수신할 Slack 채널에 대한 Incoming Webhook을 생성합니다.
2.  생성된 Webhook URL을 복사합니다. 이 URL은 Lambda 환경 변수 설정에 사용됩니다.
3.  여러 채널에 보내려면 각 채널에 대한 Webhook URL을 모두 발급받습니다.

### 2. IAM 역할(Role) 생성

Lambda 함수가 AWS 리소스에 접근할 수 있도록 IAM 역할을 생성하고 다음 정책을 연결합니다.

1.  **AWSLambdaBasicExecutionRole**: Lambda 함수가 CloudWatch Logs에 로그를 기록하기 위한 기본 권한입니다. (AWS 관리형 정책)
2.  **사용자 지정 정책**: 아래 JSON 형식의 인라인 정책을 생성하여 추가합니다.

    ```json
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:DescribeAlarmHistory",
                    "cloudwatch:GetMetricStatistics",
                    "ec2:DescribeInstances"
                ],
                "Resource": "*"
            }
        ]
    }
    ```

    -   `cloudwatch:DescribeAlarmHistory`: 경보의 최근 상태 변경 이력을 가져옵니다.
    -   `cloudwatch:GetMetricStatistics`: 다중 지표 경보 발생 시 각 지표의 최신 값을 가져옵니다.
    -   `ec2:DescribeInstances`: EC2 인스턴스 ID를 `Name` 태그 값으로 변환합니다.

### 3. Lambda 함수 생성 및 구성

1.  AWS Lambda 콘솔에서 **새 함수를 생성**합니다.
    -   **함수 이름**: `SNS-to-Slack-Notifier` 등 식별하기 쉬운 이름으로 지정합니다.
    -   **런타임**: `Python 3.9` 이상을 선택합니다.
    -   **아키텍처**: `x86_64` 또는 `arm64`를 선택합니다.
    -   **실행 역할**: 위에서 생성한 IAM 역할을 선택합니다.

2.  **코드 소스**에 `lambda_function.py` 파일의 전체 코드를 붙여넣고 **Deploy** 버튼을 누릅니다.

3.  **환경 변수**를 설정합니다. (`구성` > `환경 변수` > `편집`)
    -   **키**: `SLACK_WEBHOOK_URL`
    -   **값**: 1단계에서 발급받은 Slack Webhook URL을 입력합니다.
        -   여러 채널로 보내려면 쉼표(`,`)로 구분하여 URL을 나열합니다.
          (예: `https://hooks.slack.com/services/T000.../B000.../XXXX,https://hooks.slack.com/services/T000.../B000.../YYYY`)

4.  **기본 설정**을 수정합니다. (`구성` > `일반 구성` > `편집`)
    -   **제한 시간**: `10초` 정도로 설정하는 것을 권장합니다. (API 호출 시간에 따라 조정)

### 4. SNS 주제(Topic) 생성 및 Lambda 구독

1.  Amazon SNS 콘솔에서 **새 주제를 생성**합니다. (예: `CloudWatch-Alarms-Topic`)
2.  생성된 주제의 **구독(Subscriptions)** 탭에서 **구독 생성**을 클릭합니다.
    -   **프로토콜**: `AWS Lambda`
    -   **엔드포인트**: 위에서 생성한 Lambda 함수의 ARN을 선택합니다.
3.  구독을 생성하면 Lambda 함수에 SNS를 트리거로 추가하기 위한 권한이 자동으로 설정됩니다.

### 5. CloudWatch 경보에 SNS 액션 추가

1.  알림을 받고자 하는 CloudWatch 경보를 선택하고 **편집**을 클릭합니다.
2.  **작업 구성** 단계에서 **알림 보내기** 대상을 위에서 생성한 **SNS 주제**로 지정합니다.
3.  경보 상태가 `경보`, `확인`, `데이터 부족` 중 하나로 변경될 때마다 해당 SNS 주제로 메시지가 전송되고, 이어서 Lambda 함수가 실행되어 Slack으로 알림을 보내게 됩니다.

## 코드 개선 제안

현재 코드의 `get_instance_name` 함수는 EC2 인스턴스 정보를 가져오기 위해 `boto3.client('ec2')`를 호출합니다. 이 부분은 개선의 여지가 있습니다.

### 문제점
- `boto3.client()`는 호출될 때마다 새로운 클라이언트 세션을 생성할 수 있어 미세한 오버헤드가 발생합니다.
- 코드 전반에 걸쳐 `boto3.client()`와 `boto3.session.Session()`이 혼용되고 있어 일관성이 부족합니다.

### 개선 방안
`lambda_handler` 상단에서 생성된 `boto3` 클라이언트를 `get_instance_name` 함수에 인자로 전달하여 재사용하는 것이 좋습니다. 이렇게 하면 코드의 일관성을 높이고 잠재적인 성능 저하를 방지할 수 있습니다.

`lambda_function.py`의 `2026-01-22-client-reuse` 버전에서 해당 내용이 반영되었습니다.