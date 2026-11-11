package com.example.pleosprojectv01

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newFixedThreadPool(2)
    private val prefs by lazy { getSharedPreferences("convoy", MODE_PRIVATE) }
    private var session: ConvoySession? = null
    private var room: JSONObject? = null
    private var generation = 0
    private var busy = false
    private var polling = false
    private var running = false
    private var latestLocation: JSONObject? = null
    private var revision = -1L
    private var lastAlert = ""
    private var reviewProposalId: String? = null
    private var gleoRequest: String? = null
    private lateinit var location: PleosLocation
    private lateinit var navigation: PleosNavigation
    private lateinit var status: TextView
    private lateinit var navStatus: TextView
    private lateinit var locationStatus: TextView
    private lateinit var serverInput: EditText
    private lateinit var nameInput: EditText
    private lateinit var codeInput: EditText
    private lateinit var connectionBox: LinearLayout
    private lateinit var sessionTitle: TextView
    private lateinit var membersBox: LinearLayout
    private lateinit var proposalBox: LinearLayout
    private lateinit var candidatesBox: LinearLayout
    private lateinit var realLocation: CheckBox
    private lateinit var demoLocation: CheckBox
    private lateinit var realSearch: CheckBox
    private lateinit var demoLat: EditText
    private lateinit var demoLon: EditText

    private val tick = object : Runnable {
        override fun run() {
            if (!running) return
            poll()
            main.postDelayed(this, 3000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.decorView.setBackgroundColor(Color.rgb(243, 246, 250))
        buildScreen()
        val code = prefs.getString("code", "").orEmpty()
        if (code.isNotEmpty()) session = ConvoySession(prefs.getString("server", "http://10.0.2.2:8765")!!,
            code, prefs.getString("member_id", "")!!, prefs.getString("token", "")!!)
        location = PleosLocation(this, { data -> main.post {
            if (realLocation.isChecked) {
                latestLocation = JSONObject().put("latitude", data.latitude).put("longitude", data.longitude)
                    .put("measured_at", data.timestampMillis / 1000.0).put("source", "sdk")
                locationStatus.text = String.format(Locale.US, "SDK 위치 %.5f, %.5f", data.latitude, data.longitude)
            }
        } }, { message -> main.post { locationStatus.text = message } })
        navigation = PleosNavigation(this) { /* Legacy SDK retained for the opt-in probe only. */ }
        showSession()
        handleGleo(intent)
        // Explicit debug launcher only; a normal app launch keeps the existing home screen.
        if (BuildConfig.DEBUG && session != null) when (intent.getStringExtra("demo_screen")) {
            "native" -> startActivity(Intent(this, NativeTmapActivity::class.java)
                .putExtra("external_gps_replay", true).putExtra("follow_plan", true))
            "map" -> startActivity(Intent(this, JourneyActivity::class.java)
                .putExtra("auto_refresh_plan", true))
        }
    }

    private fun buildScreen() {
        val content = column().apply { setPadding(dp(24), dp(12), dp(24), dp(24)) }
        setContentView(ScrollView(this).apply { addView(content) })
        content.addView(label("같이 가요", 30f))
        content.addView(label("동행 차량과 위치를 나누고, 함께 들를 곳을 결정하세요.", 17f))
        status = label("서버를 시작한 뒤 모임을 만들거나 참가하세요.", 17f)
        content.addView(status)
        val columns = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        content.addView(columns)
        val left = column()
        val right = column()
        columns.addView(left, LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = dp(16) })
        columns.addView(right, LinearLayout.LayoutParams(0, -2, 1.2f))
        val connectionCard = card(left, "동행 모임")
        sessionTitle = label("참가한 모임 없음", 22f)
        connectionCard.addView(sessionTitle)
        connectionBox = column()
        connectionCard.addView(connectionBox)
        serverInput = field("서버 주소", prefs.getString("server", "http://10.0.2.2:8765").orEmpty())
        nameInput = field("내 차량 이름", prefs.getString("name", "차량 A").orEmpty())
        codeInput = field("초대 코드", "")
        connectionBox.addView(serverInput); connectionBox.addView(nameInput); connectionBox.addView(codeInput)
        button(connectionBox, "새 모임 만들기") {
            pointDialog("공동 목적지", "테스트 목적지", "37.48544722", "127.03636666") { destination ->
                val server = runCatching { ConvoyApi.validateServer(serverInput.text.toString()) }.getOrElse { showError(it); return@pointDialog }
                perform("모임 만드는 중", { ConvoyApi.request(server, "/rooms", JSONObject().put("name", nameInput.text.toString()).put("destination", destination)) }) { acceptSession(server, it) }
            }
        }
        button(connectionBox, "초대 코드로 참가") {
            val server = runCatching { ConvoyApi.validateServer(serverInput.text.toString()) }.getOrElse { showError(it); return@button }
            val code = codeInput.text.toString().trim().uppercase(Locale.ROOT)
            if (!code.matches(Regex("[A-F0-9]{8}"))) { status.text = "초대 코드 8자리를 확인하세요."; return@button }
            perform("모임 참가 중", { ConvoyApi.request(server, "/rooms/$code/join", JSONObject().put("name", nameInput.text.toString())) }) { acceptSession(server, it) }
        }
        button(connectionCard, "모임 나가기 / 연결 정보 초기화") {
            val current = session ?: return@button
            AlertDialog.Builder(this).setTitle("모임 나가기").setMessage("연결이 안 되면 이 기기의 연결 정보만 초기화할 수도 있습니다.")
                .setPositiveButton("서버에서 나가기") { _, _ -> perform("모임 나가는 중", { ConvoyApi.room(current, "leave", JSONObject()) }) { clearSession() } }
                .setNeutralButton("기기 정보만 초기화") { _, _ -> clearSession() }.setNegativeButton("취소", null).show()
        }

        val locationCard = card(left, "내 위치 공유")
        locationCard.addView(label("위치는 참가한 모임에서만 공유됩니다. 앱 화면을 벗어나면 위치 전송과 모임 알림이 멈춥니다.", 15f))
        locationStatus = label("위치 공유 꺼짐", 17f)
        locationCard.addView(locationStatus)
        realLocation = CheckBox(this).apply {
            text = "실제 차량 위치 공유"; minHeight = dp(56)
            setOnCheckedChangeListener { _, checked ->
                latestLocation = null
                if (checked) {
                    demoLocation.isChecked = false
                    if (checkSelfPermission(LOCATION_PERMISSION) == PackageManager.PERMISSION_GRANTED) location.start()
                    else requestPermissions(arrayOf(LOCATION_PERMISSION), 7)
                } else { location.stop(); locationStatus.text = "위치 공유 꺼짐" }
            }
        }
        locationCard.addView(realLocation)
        demoLocation = CheckBox(this).apply {
            text = "테스트 위치 공유 (실제 GPS 아님)"; minHeight = dp(56)
            visibility = if (BuildConfig.DEBUG) View.VISIBLE else View.GONE
            setOnCheckedChangeListener { _, checked ->
                if (checked) { realLocation.isChecked = false; latestLocation = null; locationStatus.text = "테스트 좌표 공유 중" }
            }
        }
        locationCard.addView(demoLocation)
        if (BuildConfig.DEBUG) {
            val coords = LinearLayout(this)
            demoLat = field("테스트 위도", "37.52", true); demoLon = field("테스트 경도", "127.06", true)
            coords.addView(demoLat, LinearLayout.LayoutParams(0, -2, 1f)); coords.addView(demoLon, LinearLayout.LayoutParams(0, -2, 1f))
            locationCard.addView(coords)
        }
        membersBox = card(right, "동행 차량")
        proposalBox = card(right, "경유지 제안과 반영 상태")
        val searchCard = card(left, "함께 들를 곳 찾기")
        realSearch = CheckBox(this).apply { text = "실제 장소 검색 (TMAP)"; isChecked = true; minHeight = dp(56) }
        searchCard.addView(realSearch)
        searchCard.addView(label("실제 검색은 TMAP에 차량 위치·목적지·경유지를 보내 도로 우회·대기 시간을 비교합니다. 해제하면 테스트 좌표입니다.", 15f))
        button(searchCard, "휴게소 후보 찾기") { search("rest_stop") }
        button(searchCard, "음식점 후보 찾기") { search("restaurant") }
        button(searchCard, "좌표로 경유지 직접 제안") { pointDialog("경유지", "", "", "") { propose(it) } }
        candidatesBox = column(); searchCard.addView(candidatesBox)
        val sdkCard = card(right, "TMAP 동행 경로")
        navStatus = label("차량별 현재 위치에서 TMAP 도로 경로를 계산합니다.", 17f); sdkCard.addView(navStatus)
        button(sdkCard, "정식 TMAP 내비 SDK") {
            startActivity(Intent(this, NativeTmapActivity::class.java))
        }
        button(sdkCard, "TMAP 동행 지도 · ETA · 합류 후보") { openJourney() }
        sdkCard.addView(label("지도에서 카페·휴게소·충전소 후보, 우회·대기 시간, 선두 차량 계획과 약속 시각을 확인하세요. 전원 승인 후 각자 앱 경로에 반영합니다. 회전별 음성 길안내와 차량 기본 내비 변경은 제공하지 않습니다.", 15f))
    }

    override fun onStart() {
        super.onStart(); running = true
        if (realLocation.isChecked && checkSelfPermission(LOCATION_PERMISSION) == PackageManager.PERMISSION_GRANTED) location.start()
        main.post(tick)
    }
    override fun onStop() {
        running = false; main.removeCallbacks(tick); location.stop(); latestLocation = null
        super.onStop()
    }
    override fun onDestroy() { navigation.close(); io.shutdown(); super.onDestroy() }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 7) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED && realLocation.isChecked && running) location.start()
            else { realLocation.isChecked = false; locationStatus.text = "위치 권한이 필요합니다. 테스트 위치로도 확인할 수 있습니다." }
        }
    }

    private fun acceptSession(server: String, response: JSONObject) {
        session = ConvoySession(server, response.getString("code"), response.getString("member_id"), response.getString("token"))
        generation++; revision = -1
        prefs.edit().putString("server", server).putString("code", session!!.code).putString("member_id", session!!.memberId)
            .putString("token", session!!.token).putString("name", nameInput.text.toString()).apply()
        showSession(); updateRoom(response.getJSONObject("room"))
    }
    private fun clearSession() {
        realLocation.isChecked = false; demoLocation.isChecked = false
        session = null; room = null; generation++; revision = -1
        prefs.edit().remove("code").remove("member_id").remove("token").apply()
        showSession(); membersBox.removeAllViews(); proposalBox.removeAllViews(); candidatesBox.removeAllViews()
        status.text = "연결 정보를 초기화했습니다."
    }
    private fun showSession() {
        connectionBox.visibility = if (session == null) View.VISIBLE else View.GONE
        sessionTitle.text = session?.let { "초대 코드  ${it.code}" } ?: "참가한 모임 없음"
    }

    private fun perform(message: String, work: () -> JSONObject, done: (JSONObject) -> Unit) {
        if (busy) { status.text = "앞선 요청을 처리 중입니다."; return }
        busy = true; status.text = message
        val expected = generation
        io.execute {
            val result = runCatching(work)
            main.post {
                busy = false
                if (!isDestroyed && generation == expected) result.onSuccess {
                    runCatching { done(it); status.text = "모임 정보가 갱신되었습니다." }.onFailure { actionFailed(it) }
                }.onFailure { actionFailed(it) }
            }
        }
    }
    private fun poll() {
        val current = session ?: return
        if (polling) return
        val expected = generation
        val snapshotLocation = if (BuildConfig.DEBUG && demoLocation.isChecked) runCatching {
            JSONObject().put("latitude", demoLat.text.toString().toDouble()).put("longitude", demoLon.text.toString().toDouble())
                .put("measured_at", System.currentTimeMillis() / 1000.0).put("source", "demo")
        }.getOrNull() else latestLocation?.takeIf { System.currentTimeMillis() / 1000.0 - it.optDouble("measured_at") in 0.0..30.0 }
        polling = true
        io.execute {
            val result = runCatching { if (snapshotLocation == null) ConvoyApi.room(current) else ConvoyApi.room(current, "location", snapshotLocation) }
            main.post {
                polling = false
                if (!isDestroyed && running && generation == expected) result.onSuccess { updateRoom(it) }.onFailure { showError(it) }
            }
        }
    }

    private fun updateRoom(value: JSONObject) {
        if (value.optString("code") != session?.code) return
        val incoming = value.optLong("revision", 0)
        if (incoming < revision) return
        revision = incoming; room = value
        val members = value.getJSONObject("members")
        membersBox.removeAllViews()
        membersBox.addView(label("동행 차량 · ${members.length()}대", 22f))
        membersBox.addView(label("목적지: ${value.getJSONObject("destination").getString("name")}", 17f))
        for (id in members.keys()) {
            val member = members.getJSONObject(id)
            val loc = member.optJSONObject("location")
            val locationText = if (loc == null) "위치 공유 대기" else {
                val age = ((System.currentTimeMillis() / 1000.0 - loc.getDouble("measured_at")).coerceAtLeast(0.0)).toInt()
                val prefix = if (loc.optString("source") == "demo") "테스트" else "GPS"
                String.format(Locale.US, "%s %.5f, %.5f · %d초 전%s", prefix, loc.getDouble("latitude"), loc.getDouble("longitude"), age,
                    if (age > 30) " · 오래된 위치" else "")
            }
            val seenAge = System.currentTimeMillis() / 1000.0 - member.getDouble("last_seen")
            membersBox.addView(label("${member.getString("name")}${if (id == session?.memberId) " (나)" else ""}${if (seenAge > 15) " · 연결 확인 필요" else ""}\n$locationText", 17f))
        }
        renderProposal(value.optJSONObject("proposal"))
    }

    private fun renderProposal(proposal: JSONObject?) {
        proposalBox.removeAllViews(); proposalBox.addView(label("경유지 제안", 22f))
        if (proposal == null) { proposalBox.addView(label("함께 들를 장소를 찾아 제안해 보세요.", 17f)); return }
        val place = proposal.getJSONObject("place")
        val id = proposal.getString("id")
        val state = proposal.getString("status")
        proposalBox.addView(label(place.getString("name"), 23f))
        proposalBox.addView(label("${sourceLabel(place)} · ${stateLabel(state)}", 17f))
        val members = room!!.getJSONObject("members")
        val votes = proposal.getJSONObject("votes")
        val applications = proposal.getJSONObject("applications")
        for (memberId in votes.keys()) {
            val vote = if (votes.isNull(memberId)) "응답 대기" else if (votes.getBoolean(memberId)) "승인" else "거절"
            val application = applications.getJSONObject(memberId)
            proposalBox.addView(label("${members.optJSONObject(memberId)?.optString("name") ?: "나간 차량"}: $vote / ${stateLabel(application.getString("state"))}\n${application.optString("detail")}", 17f))
        }
        val me = session!!.memberId
        if (state == "pending" && votes.has(me) && votes.isNull(me)) {
            button(proposalBox, "이 경유지 승인") { decide(id, true) }
            button(proposalBox, "이 경유지 거절") { decide(id, false) }
        }
        if (state == "pending" && proposal.getString("proposer_id") == me) button(proposalBox, "제안 취소") {
            val current = session ?: return@button
            perform("제안 취소 중", { ConvoyApi.room(current, "cancel", JSONObject().put("proposal_id", id)) }) { updateRoom(it) }
        }
        val ownState = applications.optJSONObject(me)?.optString("state")
        if (state in listOf("approved", "completed") && ownState in listOf("not_requested", "failed", "unconfirmed")) {
            button(proposalBox, if (ownState == "not_requested") "내 앱 경로에 반영" else "앱 경로 다시 요청") {
                AlertDialog.Builder(this).setTitle("TMAP 앱 경로 계산")
                    .setMessage("승인된 목적지와 경유지 순서로 내 차량의 도로 경로를 계산합니다. 차량 기본 내비는 변경되지 않습니다.\n${sourceLabel(place)}")
                    .setPositiveButton("경로 변경 요청") { _, _ -> applyRoute(id) }.setNegativeButton("취소", null).show()
            }
        }
        if (state == "pending" && proposal.getString("proposer_id") != me && id != lastAlert && running) {
            lastAlert = id
            val tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 35)
            tone.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
            main.postDelayed({ tone.release() }, 200)
            showProposalPrompt(proposal)
        }
    }
    private fun showProposalPrompt(proposal: JSONObject) {
        val id = proposal.getString("id")
        AlertDialog.Builder(this).setTitle("함께 들를 장소가 제안되었습니다")
            .setMessage("${proposal.getJSONObject("place").getString("name")}\n${sourceLabel(proposal.getJSONObject("place"))}\n승인 후 전원 동의가 모여야 경로를 변경할 수 있습니다.")
            .setPositiveButton("승인") { _, _ -> decide(id, true) }.setNegativeButton("거절") { _, _ -> decide(id, false) }
            .setNeutralButton("나중에 확인", null).show()
    }
    private fun decide(id: String, approve: Boolean) {
        val current = session ?: return
        perform("응답 전달 중", { ConvoyApi.room(current, "decisions", JSONObject().put("proposal_id", id).put("approve", approve)) }) {
            updateRoom(it)
            if (reviewProposalId == id) { respondGleo("REVIEW_CONVOY_PROPOSAL", "success", "The driver's decision has been recorded."); reviewProposalId = null }
        }
    }
    private fun applyRoute(id: String) {
        val current = session ?: return
        perform("경로 요청을 등록하는 중", { ConvoyApi.room(current, "applications", JSONObject().put("proposal_id", id).put("state", "requested")) }) { response ->
            updateRoom(response)
            val proposal = response.getJSONObject("proposal")
            val attempt = proposal.getJSONObject("applications").getJSONObject(current.memberId).getString("attempt_id")
            perform("TMAP 도로 경로 계산 중", {
                val route = runCatching { ConvoyApi.room(current, "journey", JSONObject().put("action", "apply")
                    .put("proposal_id", id).put("attempt_id", attempt)) }
                val detail = route.fold(onSuccess = { val r = it.getJSONObject("route")
                    "TMAP 앱 경로 준비 완료 · ${Math.round(r.getDouble("meters")/1000)}km / ${Math.round(r.getDouble("seconds")/60)}분 · 차량 기본 내비 변경 아님"
                }, onFailure = { "TMAP 경로 실패: ${it.message}" })
                ConvoyApi.room(current, "applications", JSONObject().put("proposal_id", id).put("attempt_id", attempt)
                    .put("state", if (route.isSuccess) "succeeded" else "failed").put("detail", detail))
            }) { updateRoom(it); navStatus.text = it.getJSONObject("proposal").getJSONObject("applications")
                .getJSONObject(current.memberId).getString("detail") }
        }
    }

    private fun openJourney() {
        if (session == null) { status.text = "먼저 모임에 참가하세요."; return }
        startActivity(Intent(this, JourneyActivity::class.java).putExtra("share_location", realLocation.isChecked))
    }

    private fun search(category: String, gleo: Boolean = false, query: String = "", mode: String = "middle", parking: Int = 0) {
        val current = session ?: run { status.text = "먼저 모임에 참가하세요."; return }
        val source = if (realSearch.isChecked || gleo) "tmap" else "demo"
        perform("공동 후보 찾는 중", { if (source == "tmap") ConvoyApi.room(current, "journey", JSONObject().put("action", "suggest").put("category", category)
            .put("query", query).put("mode", mode).put("parking_cars", parking))
            else ConvoyApi.room(current, "candidates", JSONObject().put("category", category).put("source", source)) }) { result ->
            candidatesBox.removeAllViews()
            candidatesBox.addView(label(result.getString("basis"), 16f)); candidatesBox.addView(label(result.getString("attribution"), 14f))
            val candidates = result.getJSONArray("candidates")
            if (candidates.length() == 0) candidatesBox.addView(label("주변에서 후보를 찾지 못했습니다. 좌표로 직접 제안할 수 있습니다.", 17f))
            for (i in 0 until candidates.length()) {
                val candidate = candidates.getJSONObject(i)
                val basis = if (source == "tmap") "최대 우회 ${Math.round(candidate.getDouble("max_detour_seconds")/60)}분 · 대기 ${Math.round(candidate.getDouble("wait_seconds")/60)}분"
                    else "차량별 직선거리 중 최대 ${candidate.getDouble("max_straight_km")}km"
                button(candidatesBox, "${candidate.getString("name")}\n$basis · 제안") { propose(candidate) }
            }
            if (gleo) respondGleo("FIND_MEETING_PLACES", "success", if (source == "demo")
                "Test coordinate candidates are shown on screen. These are not real places."
                else "TMAP candidates with estimated driving detours and waiting times are shown on screen. Parking availability is unverified.")
        }
    }
    private fun propose(place: JSONObject) {
        val current = session ?: run { status.text = "먼저 모임에 참가하세요."; return }
        AlertDialog.Builder(this).setTitle("일행에게 경유지 제안")
            .setMessage("${place.getString("name")}\n${sourceLabel(place)}\n제안하면 내 차량은 승인한 것으로 기록합니다.")
            .setPositiveButton("제안 보내기") { _, _ -> perform("제안 전달 중", { ConvoyApi.room(current, "proposals", JSONObject().put("place", place)) }) { updateRoom(it) } }
            .setNegativeButton("취소", null).show()
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handleGleo(intent) }
    private fun handleGleo(intent: Intent?) {
        val action = intent?.action ?: return
        if (action !in listOf("SHOW_CONVOY_STATUS", "FIND_MEETING_PLACES", "REVIEW_CONVOY_PROPOSAL")) return
        val current = session ?: run { respondGleo(action, "fail", "Join a convoy on screen first."); return }
        if (busy) { respondGleo(action, "fail", "Another request is in progress. Try again shortly."); return }
        val raw = intent.getStringExtra("ACTION_PARAM")
        val params = runCatching {
            if (raw == null) JSONObject() else {
                val value = org.json.JSONTokener(raw).nextValue()
                if (value is String) JSONObject(value) else value as JSONObject
            }
        }.getOrElse { respondGleo(action, "fail", "The action parameters are invalid."); return }
        gleoRequest = action
        if (action == "FIND_MEETING_PLACES") {
            val category = params.optString("category", intent.getStringExtra("category") ?: "rest_stop")
            if (category !in listOf("rest_stop", "restaurant", "cafe", "charging", "parking")) { respondGleo(action, "fail", "Choose a supported place category."); return }
            search(category, true, params.optString("query"), params.optString("mode", "middle"), params.optInt("parking_cars", 0))
        } else perform("음성 요청 확인 중", {
            if (action == "SHOW_CONVOY_STATUS") ConvoyApi.room(current, "journey", JSONObject().put("action", "overview"))
            else ConvoyApi.room(current)
        }) { response ->
            if (action == "SHOW_CONVOY_STATUS") {
                val delay = Math.round(response.getDouble("arrival_spread_seconds")/60)
                val routeCount = response.getJSONObject("routes").length()
                navStatus.text = "TMAP 교통 예상 · ${routeCount}대 도착 차이 ${delay}분 · 지도에서 차량별 시간 확인"
                respondGleo(action, "success", "TMAP 교통 예상으로 일행의 도착 시간 차이는 약 ${delay}분입니다.",
                    JSONArray().put(JSONObject().put("vehicleCount", routeCount).put("arrivalSpreadMinutes", delay)))
            }
            else {
                updateRoom(response)
                val proposal = response.optJSONObject("proposal")
                if (proposal == null || proposal.optString("status") != "pending") respondGleo(action, "fail", "There is no pending proposal to review.")
                else { reviewProposalId = proposal.getString("id"); showProposalPrompt(proposal)
                    respondGleo(action, "asking", "Review the proposal on screen and choose approve or decline.") }
            }
        }
    }
    private fun respondGleo(action: String, result: String, message: String, data: JSONArray? = null) {
        if (gleoRequest == action) gleoRequest = null
        val response = JSONObject().put("functionName", action).put("status", result).put("message", message)
        data?.let { response.put("data", it.toString()) }
        // Public callback protocol: never include tokens, invitation codes, names, or locations.
        sendBroadcast(Intent("ai.pleos.playground.intent.action.APP_ACTION_RESPONSE")
            .putExtra("packageName", packageName).putExtra("response", response.toString()))
    }

    private fun pointDialog(title: String, name: String, lat: String, lon: String, accept: (JSONObject) -> Unit) {
        val form = column().apply { setPadding(dp(20), 0, dp(20), 0) }
        val nameField = field("장소 이름", name); val latField = field("위도", lat, true); val lonField = field("경도", lon, true)
        form.addView(nameField); form.addView(latField); form.addView(lonField)
        if (name == "테스트 목적지") form.addView(label("기본 좌표는 실행 확인용입니다. 실제 이동 목적지에 맞게 수정하세요.", 15f))
        val dialog = AlertDialog.Builder(this).setTitle(title).setView(form).setPositiveButton("확인", null).setNegativeButton("취소", null).create()
        dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            runCatching {
                val latitude = latField.text.toString().toDouble(); val longitude = lonField.text.toString().toDouble()
                require(nameField.text.isNotBlank() && nameField.text.length <= 100 && latitude.isFinite() && longitude.isFinite() && latitude in -90.0..90.0 && longitude in -180.0..180.0) { "장소 이름과 좌표 범위를 확인하세요." }
                val point = JSONObject().put("name", nameField.text.toString()).put("latitude", latitude).put("longitude", longitude).put("source", "manual")
                dialog.dismiss(); accept(point)
            }.onFailure { nameField.error = it.message ?: "입력을 확인하세요." }
        } }
        dialog.show()
    }
    private fun sourceLabel(place: JSONObject) = when (place.optString("source")) {
        "demo" -> "테스트 좌표 · 실제 장소 아님"
        "osm" -> "OpenStreetMap 장소 · 진입 방향/영업 여부 미확인"
        "tmap" -> "TMAP 장소 · 진입 방향/주차·영업 여부 확인 필요"
        else -> "직접 지정한 좌표"
    }
    private fun stateLabel(state: String) = when (state) {
        "pending" -> "일행 응답 대기"
        "approved" -> "전원 승인 · 각 차량 반영 대기"
        "rejected" -> "거절된 제안"
        "cancelled" -> "취소된 제안"
        "completed" -> "차량별 처리 종료 · 아래 결과 확인"
        "not_requested" -> "반영 요청 전"
        "requested" -> "앱 경로 계산 중"
        "succeeded" -> "앱 경로 준비 완료"
        "failed" -> "반영 실패"
        "unconfirmed" -> "반영 확인 불가"
        else -> state
    }
    private fun showError(error: Throwable) { status.text = error.message ?: "연결에 실패했습니다." }
    private fun actionFailed(error: Throwable) {
        showError(error)
        gleoRequest?.let { respondGleo(it, "fail", "The request could not be completed. Check the convoy connection on screen.") }
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun label(value: String, size: Float) = TextView(this).apply {
        text = value; textSize = size; setTextColor(Color.rgb(32, 50, 74)); setPadding(0, dp(6), 0, dp(8))
    }
    private fun card(parent: LinearLayout, title: String) = column().apply {
        setBackgroundColor(Color.WHITE); setPadding(dp(16), dp(12), dp(16), dp(16))
        parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(16) }); addView(label(title, 22f))
    }
    private fun field(hintText: String, value: String, numeric: Boolean = false) = EditText(this).apply {
        hint = hintText; setText(value); textSize = 17f; minHeight = dp(56); isSingleLine = true
        inputType = if (numeric) InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL or InputType.TYPE_NUMBER_FLAG_SIGNED else InputType.TYPE_CLASS_TEXT
    }
    private fun button(parent: LinearLayout, title: String, action: () -> Unit) = Button(this).apply {
        text = title; isAllCaps = false; textSize = 17f; minHeight = dp(60); setTextColor(Color.rgb(8, 100, 115))
        setOnClickListener { action() }; parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }
    companion object { private const val LOCATION_PERMISSION = "pleos.car.permission.FUSED_LOCATION" }
}
