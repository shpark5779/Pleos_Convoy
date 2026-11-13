package com.example.pleosprojectv01

import android.app.Activity
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors

/** Foreground GPS sender: does not initialize either navigation SDK or request a route. */
class GpsShareActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private lateinit var location: PleosLocation
    private lateinit var status: TextView
    private lateinit var planControls: ConvoyPlanControls
    private var point: JSONObject? = null
    private var visible = false
    private var sending = false
    private val tick = object : Runnable {
        override fun run() {
            if (!visible) return
            sendLocation()
            main.postDelayed(this, 3000)
        }
    }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val column = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32,32,32,32) }
        column.addView(TextView(this).apply { text = "GPS 전용 · 동행 차량 위치 전송"; textSize = 26f })
        column.addView(TextView(this).apply { text = "이 화면을 켜 두면 3초마다 참가한 모임에 GPS를 공유합니다. 내비 경로는 요청하지 않습니다. 화면을 벗어나면 전송이 중지됩니다."; textSize = 20f })
        status = TextView(this).apply { text = "GPS 수신 대기"; textSize = 24f }
        column.addView(status)
        planControls=ConvoyPlanControls(this);column.addView(planControls)
        column.addView(Button(this).apply { text = "전송 종료"; setOnClickListener { finish() } })
        setContentView(column)
        location = PleosLocation(this, { p -> main.post {
            point = JSONObject().put("latitude",p.latitude).put("longitude",p.longitude)
                .put("measured_at",p.timestampMillis / 1000.0).put("source","sdk")
        } }, { message -> main.post { if (visible) status.text = message } })
    }
    override fun onStart() {
        super.onStart(); visible = true
        if (checkSelfPermission("pleos.car.permission.FUSED_LOCATION") == PackageManager.PERMISSION_GRANTED) location.start()
        else requestPermissions(arrayOf("pleos.car.permission.FUSED_LOCATION"), 7)
        main.post(tick)
    }
    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code,permissions,results)
        if (code == 7 && visible && results.firstOrNull() == PackageManager.PERMISSION_GRANTED) location.start()
        else if (code == 7) status.text = "위치 권한이 필요합니다. 종료 후 다시 열어 주세요."
    }
    override fun onStop() {
        visible = false; main.removeCallbacks(tick); location.stop(); point = null; super.onStop()
    }
    override fun onDestroy() { planControls.close();io.shutdown(); super.onDestroy() }

    private fun sendLocation() {
        if (sending) return
        val prefs = getSharedPreferences("convoy",MODE_PRIVATE)
        val code = prefs.getString("code","").orEmpty()
        if (code.isEmpty()) { status.text = "메인 화면에서 먼저 모임에 참가하세요."; return }
        val data = point?.takeIf { System.currentTimeMillis()/1000.0 - it.optDouble("measured_at") in -5.0..30.0 }
        if (data == null) { status.text = "최근 GPS 수신 대기 · 오래된 좌표는 보내지 않습니다."; return }
        val session = ConvoySession(prefs.getString("server","http://10.0.2.2:8765")!!,code,
            prefs.getString("member_id","")!!,prefs.getString("token","")!!)
        sending = true
        io.execute {
            val result = runCatching { ConvoyApi.room(session,"location",data) }
            main.post {
                sending = false
                if(visible)result.onSuccess { planControls.update(it) }
                if (visible) status.text = if (result.isSuccess)
                    "GPS 전송 완료 · %.5f, %.5f".format(java.util.Locale.US,data.getDouble("latitude"),data.getDouble("longitude"))
                    else "전송 실패 · 서버 연결 또는 모임 참가 상태를 확인하세요."
            }
        }
    }
}
