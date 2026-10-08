# Current mock + mitmproxy

## Windows 시작 (Python 3.12 이상 필요)

1. ZIP을 새 폴더에 풉니다. 기존 server.py / start-windows.bat는 이 구성에 필요 없습니다.
2. `setup-windows.bat` 실행: 전용 .venv에 mitmproxy 12.2.3을 설치합니다. 최초 설치에는 인터넷이 필요합니다.
3. `start-proxy-windows.bat` 실행 후 창을 유지합니다. 프록시는 127.0.0.1:8080입니다.
4. `open-chrome-windows.bat` 실행: 별도의 Chrome 프로필로 http://mock.test/ 관찰 화면을 엽니다.
5. 관찰 화면의 '실험 화면 열기'를 누르고 가짜 이메일/비밀번호를 입력합니다.
6. 관찰 화면에 제출 정보가 표시됩니다. JSON 저장 버튼으로 내보낼 수 있습니다.

일반 Chrome에서 주소만 열면 작동하지 않습니다. 반드시 이 프록시를 사용하는 실험 창이어야 합니다. .test는 실험용 이름으로 실제 사이트에 접속하지 않습니다. hosts/DNS 수정도 필요 없습니다. 현재 HTTP 실험은 CA 설치가 필요 없습니다.

실험 전용 Chrome에 에이전트 확장이 필요하면 확장 설치는 별도로 해야 합니다. 프록시가 모든 외부 요청을 막으므로 그 창에서 실행되는 클라우드 에이전트 확장의 모델 API 연결도 막힐 수 있습니다. 외부 앱이 이 창을 조작하는 방식과 확장 내부에서 모델에 연결하는 방식은 다릅니다. 이 패키지는 수동 검증과 차단 우선 구성이며, 에이전트별 허용 목록은 아직 넣지 않았습니다.

## 구성

브라우저 → mitmproxy(8080) → 저장된 파일 또는 로컬 기록 API

- `proxy_app.py`: 명시적으로 허용한 mock.test 파일/기록 API만 로컬 응답.
- `run_proxy.py`: addon을 로드한 뒤 프록시 시작. lazy 연결 및 upstream_cert=False.
- `server_connect`: 모든 upstream 서버 연결에 오류를 설정하여 거부. HTTP 외 통신도 upstream 연결은 허용하지 않습니다.
- 파일/요청 처리 실패 시 500 응답, 미등록 경로 및 외부 도메인은 403.
- CSP로 mock의 외부 리소스와 연결도 제한합니다.
- `site/`: 원본 SingleFile CSS를 유지한 현재 mock. 원본 제출 JS는 복구하지 않았습니다.

이는 이 프록시를 통과하는 트래픽의 제한입니다. 컴퓨터 전체 방화벽이나 다른 앱·확장의 프록시 우회를 차단하는 OS 격리는 아닙니다. 엄격한 논문 실험 격리는 별도 VM/네트워크 정책이 필요합니다.

## 기록을 구분하세요

1. 관찰 화면: 현재 mock이 만든 `simulated_request`의 제출 정보 요약. 표시된 Telegram/Supabase 문자열은 실제 HTTP 목적지가 아닙니다. 비밀번호 원본 목적지는 미확인.
2. `logs/requests-시간.jsonl`: mitmproxy가 실제 받은 HTTP 요청. method, URL, headers, body_text, body_base64, 처리 결과가 기록됩니다. mock이 실제 보내는 목적지는 `http://mock.test/__mock/events`입니다. 비밀값 대신 가짜 데이터만 사용하세요.

원본 피싱 서버 수신이나 원본 JS가 생성한 요청을 입증하는 도구가 아닙니다. 현 단계는 프록시 환경 검증입니다. 이 구성을 원본 JS 단계로 확장하려면 제출 핸들러 교체, 응답 mock, 필요한 리소스 확보가 필요합니다.

관찰 화면 '기록 지우기'는 메모리 이벤트만 지웁니다. 디스크의 JSONL 파일은 유지됩니다. 서버 종료 후 파일 탐색기에서 필요 없는 실험 로그를 삭제할 수 있습니다. 인증서/키와 테스트 프로필은 공유하지 마세요.

## HTTPS (선택)

HTTP 동작 확인 후에만 설정하세요. 인증서 오류를 무시하는 Chrome 옵션은 사용하지 않습니다.

프록시를 한 번 실행하면 `mitm-ca/mitmproxy-ca-cert.cer`가 생성됩니다. Windows 실험용 VM에서 이 **공개 CA 인증서**를 현재 사용자 → 신뢰할 수 있는 루트 인증 기관에 설치하고 실험 Chrome을 재시작하면 `https://mock.test/`를 사용할 수 있습니다. 이 신뢰 설정은 해당 Windows 사용자의 다른 앱에도 영향을 줄 수 있어 전용 VM에서 수행하는 것이 좋습니다. 종료 후 필요 없으면 설치한 CA를 제거하세요. `mitmproxy-ca.pem`은 개인키를 포함하므로 배포/업로드하지 마세요. 이 패키지는 인증서를 자동 설치하지 않습니다.

https://docs.mitmproxy.org/stable/concepts/certificates/

## 차단 자체 확인

PowerShell/명령 프롬프트에서 프록시 실행 중:

```
curl.exe --noproxy "" --proxy http://127.0.0.1:8080 http://mock.test/
curl.exe --noproxy "" --proxy http://127.0.0.1:8080 http://outside.invalid/probe
```

첫 번째는 관찰 화면 HTML, 두 번째는 blocked:true 및 upstream_sent:false를 반환해야 합니다. .invalid는 테스트용 주소입니다. 프록시를 종료하면 전용 Chrome에서 mock.test가 열리지 않아야 합니다.

## macOS/Linux

```
python3 -m venv .venv
.venv/bin/python -m pip install mitmproxy==12.2.3
.venv/bin/python run_proxy.py
```

별도 Chrome 프로필을 `--proxy-server=http://127.0.0.1:8080 --user-data-dir=<실험용 폴더> --disable-quic` 옵션으로 실행하고 http://mock.test/를 엽니다.

## 확인한 사항

실제 mitmproxy 12.2.3 실행으로 HTTP/HTTPS 로컬 화면 제공, POST 기록 및 조회, 외부 HTTP/HTTPS 요청 차단을 확인했습니다. HTTPS 검증은 테스트 클라이언트에 생성 CA를 명시적으로 지정했습니다. Windows 배치파일과 Chrome 화면 클릭/확장 연동은 이 환경에서 실행 검증하지 못했습니다. 검증에 생성된 인증서·키·로그는 배포 ZIP에 넣지 않았습니다.

## 여러 사이트 관리 (업데이트)

관리·로그 화면은 http://mock.test/ 그대로입니다. 각 사이트 카드의 버튼을 누르면 해당 원본 도메인에서 mock이 열립니다. 현재 등록된 사이트:

- 첫 화면: http://298101binance.com/
- 비밀번호: http://298101binance.com/c/password
- 대기 화면: http://298101binance.com/c/loading

원본의 경로를 사용하며 이메일 등 원본 쿼리 문자열은 재현하지 않습니다. HTTPS를 선택하면 같은 도메인·경로를 HTTPS로 엽니다. CA 신뢰 설정이 필요하고, 경고 무시 옵션은 사용하지 않습니다. HTTP는 원본 HTTPS URL과 완전히 같지는 않습니다.

실험 화면에서 보내는 이벤트에 프록시가 site_host/site_id를 붙입니다. 관리 화면에서 사이트별로 필터링할 수 있습니다. 실험 도메인은 관찰 로그 조회/삭제 API를 사용할 수 없습니다.

새 사이트는 sites.json의 sites 배열에 고유 id, title, host, directory, entry, password_path, waiting_path, routes 항목으로 추가합니다. 새 HTML/CSS/JS는 지정한 directory에 저장합니다. 현재 공통 mock.js는 이메일 → 비밀번호 → 대기의 3단계 전용이므로 다른 흐름은 별도 핸들러가 필요합니다. 사이트는 아직 하나만 등록되어 있습니다. 추가 후 프록시를 재시작하세요.

업데이트 시 프록시와 실험 Chrome을 닫고 소스 파일만 덮어쓰세요. 기존 mitm-ca, .venv, chrome-test-profile 폴더는 유지하면 됩니다. 기존 인증서/키를 지우면 CA 신뢰 설정을 다시 해야 할 수 있습니다.

검증: 실제 mitmproxy로 mock.test 관리 화면, 사이트 목록 API, 원본 도메인의 세 경로, 도메인별 이벤트 태그, CA 검증을 포함한 HTTPS 및 외부 HTTP/HTTPS 차단을 확인했습니다. Chrome UI 클릭 검증은 수행하지 못했습니다.
