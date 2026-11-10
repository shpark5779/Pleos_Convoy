package com.example.pleosprojectv01

import android.content.Intent
import android.os.Build
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/** Opt-in: performs a real vendor SDK initialization, which may consume its authentication quota. */
class NativeTmapSdkProbeTest {
    @Test fun officialSdkReportsInitializationResult() {
        val i=InstrumentationRegistry.getInstrumentation()
        assumeTrue(InstrumentationRegistry.getArguments().getString("native_tmap_probe")=="true")
        val prefs=i.targetContext.getSharedPreferences("native_tmap_result",0)
        prefs.edit().clear().commit()
        i.startActivitySync(Intent(i.targetContext,NativeTmapActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        val terminal=setOf("SDK_READY","SDK_AUTH_FAILED","SDK_LIBRARY_FAILED","SDK_INITIALIZE_FAILED","KEY_REQUIRED","PERMISSION_REQUIRED")
        val deadline=System.currentTimeMillis()+90000
        while(prefs.getString("phase","") !in terminal && System.currentTimeMillis()<deadline) Thread.sleep(300)
        val phase=prefs.getString("phase","")!!
        val result=JSONObject().put("phase",phase).put("sdk_initialized",phase=="SDK_READY")
            .put("error_code",prefs.getInt("error_code",0)).put("detail",prefs.getString("detail",""))
            .put("client_id_configured",BuildConfig.TMAP_CLIENT_ID.isNotBlank())
            .put("abis",Build.SUPPORTED_ABIS.joinToString()).put("ui_sdk_version","1.0.0.0160")
        File(i.targetContext.filesDir,"native-tmap-probe.json").writeText(result.toString(2))
        assertTrue("SDK initialization must complete or report a real authorization failure: $phase",phase in setOf("SDK_READY","SDK_AUTH_FAILED"))
    }
}
