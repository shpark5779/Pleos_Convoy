package com.example.pleosprojectv01

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebResourceRequest
import android.webkit.WebChromeClient
import android.webkit.JsResult
import android.content.pm.PackageManager
import org.json.JSONObject
import java.net.URI
import java.net.URLEncoder
import java.util.concurrent.Executors

/** Same server screen on the head unit and passenger phone; no JavaScript/native bridge. */
class JourneyActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var gps: PleosLocation
    private val io = Executors.newSingleThreadExecutor()
    private var lastSent = 0L
    private var share = false
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("convoy", MODE_PRIVATE)
        val server = ConvoyApi.validateServer(prefs.getString("server", "http://10.0.2.2:8765")!!)
        val session = ConvoySession(server, prefs.getString("code", "")!!,
            prefs.getString("member_id", "")!!, prefs.getString("token", "")!!)
        share = intent.getBooleanExtra("share_location", false)
        gps = PleosLocation(this, { p ->
            val now = System.currentTimeMillis()
            if (share && now-lastSent >= 2500) {
                lastSent = now
                io.execute { runCatching { ConvoyApi.room(session, "location", JSONObject()
                    .put("latitude", p.latitude).put("longitude", p.longitude)
                    .put("measured_at", p.timestampMillis/1000.0).put("source", "sdk")) } }
            }
        }, { })
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.allowFileAccess = false
        web.settings.allowContentAccess = false
        web.webChromeClient = object : WebChromeClient() {
            override fun onJsConfirm(view: WebView, url: String, message: String, result: JsResult): Boolean {
                AlertDialog.Builder(this@JourneyActivity).setTitle("경로 변경 확인").setMessage(message)
                    .setPositiveButton("확인") { _, _ -> result.confirm() }
                    .setNegativeButton("취소") { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }.show()
                return true
            }
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                return runCatching { val uri = URI(request.url.toString())
                    uri.scheme != URI(server).scheme || uri.authority != URI(server).authority
                }.getOrDefault(true)
            }
        }
        setContentView(web)
        fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
        val autoRefresh = BuildConfig.DEBUG && intent.getBooleanExtra("auto_refresh_plan", false)
        web.loadUrl("$server/journey#code=${enc(session.code)}&member=${enc(session.memberId)}&token=${enc(session.token)}&auto_refresh=$autoRefresh")
    }
    override fun onStart() {
        super.onStart()
        if (share && checkSelfPermission("pleos.car.permission.FUSED_LOCATION") == PackageManager.PERMISSION_GRANTED) gps.start()
    }
    override fun onStop() { gps.stop(); super.onStop() }
    override fun onDestroy() { gps.stop(); web.destroy(); io.shutdown(); super.onDestroy() }
}
