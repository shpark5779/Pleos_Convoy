package com.example.pleosprojectv01

import android.app.Activity
import android.app.AlertDialog
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors

/** The same authenticated proposal/decision UI on navigation and GPS-only screens. */
class ConvoyPlanControls(private val activity:Activity) : LinearLayout(activity) {
    private val main=Handler(Looper.getMainLooper())
    private val io=Executors.newSingleThreadExecutor()
    private val summary=TextView(activity).apply { textSize=17f }
    private val propose=Button(activity).apply { text="공동 경유지 추가"; setOnClickListener { proposeDialog() } }
    private var room:JSONObject?=null
    private var prompted=""
    private var busy=false
    private var closed=false
    init { orientation=VERTICAL; addView(summary); addView(propose) }

    private fun session():ConvoySession {
        val p=activity.getSharedPreferences("convoy",Activity.MODE_PRIVATE)
        return ConvoySession(p.getString("server","http://10.0.2.2:8765")!!,p.getString("code","")!!,
            p.getString("member_id","")!!,p.getString("token","")!!)
    }
    fun update(value:JSONObject) {
        if(closed)return
        room=value
        val current=session()
        val proposal=value.optJSONObject("proposal")
        val pending=proposal?.optString("status")=="pending"
        summary.text="승인 계획 v${value.optInt("plan_version")} · 경유지 ${value.getJSONArray("waypoints").length()}개"+
            if(pending) "\n승인 요청: ${proposal!!.getJSONObject("place").optString("name")}" else ""
        propose.visibility=if(value.optString("leader_id")==current.memberId) VISIBLE else GONE
        propose.isEnabled=!busy && !pending
        val votes=proposal?.optJSONObject("votes")
        if(pending && votes?.has(current.memberId)==true && votes.isNull(current.memberId) && prompted!=proposal!!.getString("id")) {
            prompted=proposal.getString("id")
            AlertDialog.Builder(activity).setTitle("공동 경유지 승인 요청")
                .setMessage("${proposal.getJSONObject("place").getString("name")}\n전원 승인 후 이동 계획이 변경됩니다. GPS 전용 차량에는 내비 길안내가 실행되지 않습니다.")
                .setPositiveButton("승인") { _,_-> decide(proposal.getString("id"),true) }
                .setNegativeButton("거절") { _,_-> decide(proposal.getString("id"),false) }
                .setOnCancelListener { prompted="" }.show()
        }
    }
    private fun decide(id:String,approve:Boolean) {
        action("decisions",JSONObject().put("proposal_id",id).put("approve",approve))
    }
    private fun proposeDialog() {
        val column=LinearLayout(activity).apply { orientation=VERTICAL }
        fun field(label:String)=EditText(activity).apply {
            hint=label;contentDescription=label;setSingleLine(true);imeOptions=EditorInfo.IME_FLAG_NO_EXTRACT_UI
            if(label!="경유지 이름")inputType=InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL or InputType.TYPE_NUMBER_FLAG_SIGNED
            column.addView(this)
        }
        val name=field("경유지 이름"); val latitude=field("위도"); val longitude=field("경도")
        val dialog=AlertDialog.Builder(activity).setTitle("공동 경유지 제안").setView(column)
            .setNegativeButton("취소",null).setPositiveButton("제안 보내기",null).create()
        dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val lat=latitude.text.toString().toDoubleOrNull();val lon=longitude.text.toString().toDoubleOrNull()
            if(name.text.isBlank() || lat==null || lon==null || lat !in -90.0..90.0 || lon !in -180.0..180.0) {
                name.error="이름과 유효한 위도·경도를 입력하세요.";return@setOnClickListener
            }
            action("proposals",JSONObject().put("kind","stop").put("place",JSONObject()
                .put("name",name.text.toString().trim()).put("latitude",lat).put("longitude",lon)))
            dialog.dismiss()
        } }
        dialog.show()
    }
    private fun action(operation:String,body:JSONObject) {
        if(busy || closed)return
        busy=true;propose.isEnabled=false
        val current=session()
        io.execute {
            val result=runCatching { ConvoyApi.room(current,operation,body) }
            main.post {
                busy=false
                if(closed || activity.isFinishing || activity.isDestroyed)return@post
                result.onSuccess { update(it) }.onFailure {
                    summary.text="제안·승인 전송 실패. 최신 모임 상태를 확인한 뒤 다시 시도하세요."
                    prompted="";propose.isEnabled=true
                }
            }
        }
    }
    fun close() { closed=true;io.shutdown() }
}
