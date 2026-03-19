// android/app/src/main/java/com/paisa/sms/SmsReceiver.kt
//
// Fix #5: Removed reference to SmsLocalDb.getInstance() which called a class
// that was never implemented anywhere in the codebase. This caused a Kotlin
// compilation error: "Unresolved reference: SmsLocalDb".
//
// The persistLocalSms() method has been removed. The React Native bridge path
// (emitToReact) is the primary delivery mechanism. For offline persistence,
// the SMS is already queued in AsyncStorage by the JS-side sms.ts service
// after it receives the event from the bridge.
//
// TODO (future): Implement SmsLocalDb as a Room database to buffer SMS
// when the React context is unavailable (e.g. app killed during SMS receipt).

package com.paisa.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.util.Log
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.modules.core.DeviceEventManagerModule
import java.security.MessageDigest

private const val TAG = "PaisaSmsReceiver"
private const val EVENT_SMS_RECEIVED = "SMS_RECEIVED"

private val FINANCIAL_SENDER_PATTERNS = listOf(
    Regex("HDFCBK|HDFC|HDFCBNK",  RegexOption.IGNORE_CASE),
    Regex("SBIINB|SBIPSG|SBI",     RegexOption.IGNORE_CASE),
    Regex("ICICIB|ICICI",          RegexOption.IGNORE_CASE),
    Regex("AXISBK|AXIS",           RegexOption.IGNORE_CASE),
    Regex("KOTAKB|KMB",            RegexOption.IGNORE_CASE),
    Regex("PAYTM|PYTMUPI",         RegexOption.IGNORE_CASE),
    Regex("PHONEP",                RegexOption.IGNORE_CASE),
    Regex("GPAY|TEZAPP",           RegexOption.IGNORE_CASE),
    Regex("YESBK|YESBNK",         RegexOption.IGNORE_CASE),
    Regex("PNBSMS|PNB",            RegexOption.IGNORE_CASE),
    Regex("BOIIND|BOI",            RegexOption.IGNORE_CASE),
    Regex("CANBNK|CANARA",         RegexOption.IGNORE_CASE),
)

private val FINANCIAL_KEYWORDS = setOf(
    "debited", "credited", "paid", "received", "withdrawn",
    "rs.", "inr", "upi", "neft", "imps", "rtgs", "atm",
    "a/c", "account", "balance", "transaction",
)

class SmsReceiver : BroadcastReceiver() {

    companion object {
        @Volatile
        var reactContext: ReactApplicationContext? = null
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (messages.isNullOrEmpty()) return

        val sender = messages[0].originatingAddress ?: return
        val body   = messages.joinToString("") { it.messageBody }

        val isFinancialSender   = FINANCIAL_SENDER_PATTERNS.any { it.containsMatchIn(sender) }
        val bodyLower           = body.lowercase()
        val hasFinancialKeywords = FINANCIAL_KEYWORDS.any { bodyLower.contains(it) }

        if (!isFinancialSender && !hasFinancialKeywords) {
            Log.d(TAG, "Skipping non-financial SMS from: $sender")
            return
        }

        // Fix #7 (SMS hash mismatch): The local cache key is sender+body only.
        // The server computes its own canonical hash as SHA-256(user_id:device_id:body).
        // We do NOT send our local hash to the server — see sms.ts for details.
        val localCacheKey = sha256("$sender:$body")
        val timestamp = System.currentTimeMillis()

        Log.i(TAG, "Financial SMS detected from: $sender")
        emitToReact(sender, body, localCacheKey, timestamp)

        // Fix #5: Removed persistLocalSms(context, ...) call.
        // SmsLocalDb class was referenced here but never implemented,
        // causing a Kotlin compilation error. The JS-side AsyncStorage
        // queue in sms.ts handles offline buffering when the network
        // is unavailable.
    }

    private fun emitToReact(
        sender: String,
        body: String,
        localCacheKey: String,
        timestamp: Long,
    ) {
        val ctx = reactContext ?: run {
            Log.w(TAG, "ReactContext not available — SMS not forwarded to bridge")
            return
        }

        if (!ctx.hasActiveCatalystInstance()) {
            Log.w(TAG, "Catalyst not active — SMS not forwarded to bridge")
            return
        }

        try {
            val payload = Arguments.createMap().apply {
                putString("sender",         sender)
                putString("body",           body)
                putString("localCacheKey",  localCacheKey)  // Fix: renamed from "hash"
                putDouble("timestamp",      timestamp.toDouble())
            }
            ctx
                .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
                .emit(EVENT_SMS_RECEIVED, payload)

            Log.d(TAG, "SMS emitted to React Native bridge")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to emit SMS to React Native: ${e.message}")
        }
    }

    private fun sha256(input: String): String {
        val bytes = MessageDigest.getInstance("SHA-256").digest(input.toByteArray())
        return bytes.joinToString("") { "%02x".format(it) }
    }
}
