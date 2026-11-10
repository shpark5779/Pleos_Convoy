package com.example.pleosprojectv01

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI

data class ConvoySession(val server: String, val code: String, val memberId: String, val token: String)

object ConvoyApi {
    fun validateServer(value: String): String {
        val server = value.trim().trimEnd('/')
        val uri = URI(server)
        require(uri.userInfo == null && uri.query == null && uri.fragment == null && uri.path.orEmpty().isEmpty()) {
            "서버 주소에는 호스트와 포트만 입력하세요."
        }
        require(uri.host != null && (uri.scheme == "https" ||
            (BuildConfig.DEBUG && uri.scheme == "http" && uri.host in listOf("10.0.2.2", "127.0.0.1", "localhost")))) {
            "HTTPS 주소를 사용하세요. 개발 중 HTTP는 로컬 서버만 허용합니다."
        }
        return server
    }

    fun request(server: String, path: String, body: JSONObject? = null, token: String = ""): JSONObject {
        val connection = URI(validateServer(server) + path).toURL().openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 5000
            connection.readTimeout = 30000
            connection.setRequestProperty("Accept", "application/json")
            if (token.isNotEmpty()) connection.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val raw = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            val response = runCatching { JSONObject(raw) }.getOrElse { throw IllegalStateException("서버 응답을 읽지 못했습니다. HTTP $status") }
            check(status in 200..299) { response.optString("error", "서버 오류: HTTP $status") }
            return response
        } finally {
            connection.disconnect()
        }
    }

    fun room(session: ConvoySession, operation: String = "", body: JSONObject? = null): JSONObject =
        request(session.server, "/rooms/${session.code}" + if (operation.isEmpty()) "" else "/$operation", body, session.token)
}
