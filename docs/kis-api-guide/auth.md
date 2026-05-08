# KIS API - OAuth인증

| API명 | Method | URL | 실전 TR | 모의 TR |
| --- | --- | --- | --- | --- |
| 실시간 (웹소켓) 접속키 발급 | POST | `/oauth2/Approval` | `` | `` |
| 접근토큰폐기(P) | POST | `/oauth2/revokeP` | `` | `` |
| 접근토큰발급(P) | POST | `/oauth2/tokenP` | `` | `` |

---

## 실시간 (웹소켓) 접속키 발급

- **API 통신방식**: `WEBSOCKET`
- **HTTP Method**: `POST`
- **URL 명**: `/oauth2/Approval`
- **실전 Domain**: `https://openapi.koreainvestment.com:9443`
- **모의 Domain**: `https://openapivts.koreainvestment.com:29443`
- **개요**: 실시간 (웹소켓) 접속키 발급받으실 수 있는 API 입니다.
웹소켓 이용 시 해당 키를 appkey와 appsecret 대신 헤더에 넣어 API를 호출합니다.

접속키의 유효기간은 24시간이지만, 접속키는 세션 연결 시 초기 1회만 사용하기 때문에 접속키 인증 후에는 세션종료되지 않는 이상 접속키 신규 발급받지 않으셔도 365일 내내 웹소켓 데이터 수

### Request Header

| Element | 한글명 | Type | 필수 | 길이 | Description |
| --- | --- | --- | --- | --- | --- |
| `content-type` | 컨텐츠타입 | string | N | 20 | application/json; utf-8 |

### Request Body

| Element | 한글명 | Type | 필수 | 길이 | Description |
| --- | --- | --- | --- | --- | --- |
| `grant_type` | 권한부여타입 | string | Y | 18 | "client_credentials" |
| `appkey` | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| `secretkey` | 시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appsecret (절대 노출되지 않도록 주의해주세요.) * 주의 : appsecret와 secretkey는 동일하오니 착오없으시기 바랍니다. (... |

### Response Body

| Element | 한글명 | Type | 필수 | 길이 | Description |
| --- | --- | --- | --- | --- | --- |
| `approval_key` | 웹소켓 접속키 | string | Y | 286 | 웹소켓 이용 시 발급받은 웹소켓 접속키를 appkey와 appsecret 대신 헤더에 넣어 API 호출합니다. |

### Request Example (Python)

```json
{
	"grant_type": "client_credentials",
	"appkey": "PSg5dctL9dKPo727J13Ur405OSXXXXXXXXXX",
	"secretkey": "yo2t8zS68zpdjGuWvFyM9VikjXE0i0CbgPEamnqPA00G0bIfrdfQb2RUD1xP7SqatQXr1cD1fGUNsb78MMXoq6o4lAYt9YTtHAjbMoFy+c72kbq5owQY1Pvp39/x6ejpJlXCj7gE3yVOB/h25Hvl+URmYeBTfrQeOqIAOYc/OIXXXXXXXXXX"
}
```

### Response Example

```json
{
    "approval_key": "a2585daf-8c09-4587-9fce-8ab893XXXXX"
}
```

---

## 접근토큰폐기(P)

- **API 통신방식**: `REST`
- **HTTP Method**: `POST`
- **URL 명**: `/oauth2/revokeP`
- **실전 Domain**: `https://openapi.koreainvestment.com:9443`
- **모의 Domain**: `https://openapivts.koreainvestment.com:29443`
- **개요**: 부여받은 접큰토큰을 더 이상 활용하지 않을 때 사용합니다.

### Request Body

| Element | 한글명 | Type | 필수 | 길이 | Description |
| --- | --- | --- | --- | --- | --- |
| `appkey` | 고객 앱Key | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| `appsecret` | 고객 앱Secret | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appsecret (절대 노출되지 않도록 주의해주세요.) |
| `token` | 접근토큰 | string | Y | 286 | OAuth 토큰이 필요한 API 경우 발급한 Access token 일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant... |

### Response Body

| Element | 한글명 | Type | 필수 | 길이 | Description |
| --- | --- | --- | --- | --- | --- |
| `code` | 응답코드 | string | N | 8 | HTTP 응답코드 |
| `message` | 응답메세지 | string | N | 450 | 응답메세지 |

### Request Example (Python)

```json
{
  "appkey" : "PSw2UvBQCpoZFc7nZpIfIrOttmXXXXXXXXXX",
  "appsecret" : "/g84gaZp7W3DJEZhamiTH8ZdJkUJ8603rjo3HcOm5PvIc1YC3YmyJOQoW1H0kNjo4IbHwGUdi3+9oEbH4RKKl8GnEu3n/khxm0OrwHkQur+wbA74fcFXxaUnEbftu0X72Eaw9dEBMuK3rODeeOanrsJ1kZ9oKWykIG04F0nmgdXXXXXXXXXX",
  "token" : "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ0b2tlbiIsImF1ZCI6IjZmNDgxMjBiLTlmMDItNGI5ZS05MGExLTRiNDk2MGM5ZWY2MyIsImlzcyI6InVub2d3IiwiZXhwIjoxNjQzMjg2MDUzLCJpYXQiOjE2NDMxOTk2NTMsImp0aSI6IlBTdzJVdkJRQ3dvWkZhOG5acElmSXJPdHRtZUtLUGZCclNKcyJ9.6Z-UvArobBfXbnpSFbFhd9WPVEM3ZQa5NEpqfmQ6rrZBISCi-P9CEamfVReIduTVYbafF02Pl6EPXXXXXXXXXX"
}
```

### Response Example

```json
{
  "code" : 200,
  "message" : "접근토큰 폐기에 성공하였습니다"
}
```

---

## 접근토큰발급(P)

- **API 통신방식**: `REST`
- **HTTP Method**: `POST`
- **URL 명**: `/oauth2/tokenP`
- **실전 Domain**: `https://openapi.koreainvestment.com:9443`
- **모의 Domain**: `https://openapivts.koreainvestment.com:29443`
- **개요**: 본인 계좌에 필요한 인증 절차로, 인증을 통해 접근 토큰을 부여받아 오픈API 활용이 가능합니다.

1. 접근토큰(access_token)의 유효기간은 24시간 이며(1일 1회발급 원칙) 
   갱신발급주기는 6시간 입니다.(6시간 이내는 기존 발급키로 응답)

2. 접근토큰발급(/oauth2/tokenP) 시 접근토큰값(access_token)과

### Request Body

| Element | 한글명 | Type | 필수 | 길이 | Description |
| --- | --- | --- | --- | --- | --- |
| `grant_type` | 권한부여 Type | string | Y | 18 | client_credentials |
| `appkey` | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| `appsecret` | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appsecret (절대 노출되지 않도록 주의해주세요.) |

### Response Body

| Element | 한글명 | Type | 필수 | 길이 | Description |
| --- | --- | --- | --- | --- | --- |
| `access_token` | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token ex) "eyJ0eXUxMiJ9.eyJz…..................................."   ... |
| `token_type` | 접근토큰유형 | string | Y | 20 | 접근토큰유형 : "Bearer" ※ API 호출 시, 접근토큰유형 "Bearer" 입력. ex) "Bearer eyJ...." |
| `expires_in` | 접근토큰 유효기간 | number | Y | 10 | 유효기간(초) ex) 7776000 |
| `access_token_token_expired` | 접근토큰 유효기간(일시표시) | string | Y | 50 | 유효기간(년:월:일 시:분:초) ex) "2022-08-30 08:10:10" |

### Request Example (Python)

```json
{
  "grant_type": "client_credentials",
  "appkey": "PSg5dctL9dKPo727J13Ur405OSXXXXXXXXXX",
  "appsecret":  "yo2t8zS68zpdjGuWvFyM9VikjXE0i0CbgPEamnqPA00G0bIfrdfQb2RUD1xP7SqatQXr1cD1fGUNsb78MMXoq6o4lAYt9YTtHAjbMoFy+c72kbq5owQY1Pvp39/x6ejpJlXCj7gE3yVOB/h25Hvl+URmYeBTfrQeOqIAOYc/OIXXXXXXXXXX"
}
```

### Response Example

```json
{
	"access_token":"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ0b2tlbiIsImF1ZCI6ImMwNzM1NTYzLTA1MjctNDNhZS05ODRiLTJiNWI1ZWZmOWYyMyIsImlzcyI6InVub2d3IiwiZXhwIjoxNjQ5NzUxMTAwLCJpYXQiOjE2NDE5NzUxMDAsImp0aSI6IkJTZlM0QUtSSnpRVGpmdHRtdXZlenVQUTlKajc3cHZGdjBZVyJ9.Oyt_C639yUjWmRhymlszgt6jDo8fvIKkkxH1mMngunV1T15SCC4I3Xe6MXxcY23DXunzBfR1uI0KXXXXXXXXXX",
	"access_token_token_expired":"2023-12-22 08:16:59",
	"token_type":"Bearer",
	"expires_in":86400
}
```

---
