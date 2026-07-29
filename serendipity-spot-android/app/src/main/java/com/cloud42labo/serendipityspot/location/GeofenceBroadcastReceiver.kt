package com.cloud42labo.serendipityspot.location

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.cloud42labo.serendipityspot.data.SpotLocalCache
import com.cloud42labo.serendipityspot.notification.NotificationHelper
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingEvent

/**
 * システムからジオフェンス到達イベントを受け取る。
 * アプリがバックグラウンド/終了状態でも呼ばれるため、ここでは
 * ローカルキャッシュ（スプレッドシートの最新コピー）だけを参照して通知する。
 * ネットワークやサインイン状態には依存しない。
 */
class GeofenceBroadcastReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        // 何を受け取ったかは、握りつぶす場合も含めて必ず残す。
        // 「イベント自体が来ていない」のか「来ているが弾いている」のかを
        // 端末だけで切り分けられるようにするため。
        if (intent.action != ACTION_GEOFENCE_EVENT) {
            SpotLocalCache.saveLastGeofenceEvent(context, "別のaction: ${intent.action}")
            return
        }

        val geofencingEvent = GeofencingEvent.fromIntent(intent)
        if (geofencingEvent == null) {
            SpotLocalCache.saveLastGeofenceEvent(context, "中身を取り出せず")
            return
        }
        if (geofencingEvent.hasError()) {
            SpotLocalCache.saveLastGeofenceEvent(context, "エラー code=${geofencingEvent.errorCode}")
            return
        }

        val transition = geofencingEvent.geofenceTransition
        if (transition != Geofence.GEOFENCE_TRANSITION_ENTER) {
            SpotLocalCache.saveLastGeofenceEvent(context, "transition=$transition（対象外）")
            return
        }

        NotificationHelper.ensureChannel(context)
        val cachedSpots = SpotLocalCache.load(context).associateBy { it.id }
        val now = System.currentTimeMillis()

        var notified = 0
        var suppressed = 0
        var unknown = 0

        geofencingEvent.triggeringGeofences?.forEach { geofence ->
            val spot = cachedSpots[geofence.requestId]
            if (spot == null) {
                unknown++
                return@forEach
            }
            // 同じスポットで鳴り続けないようにする。出入りを繰り返す場所でも
            // 一定時間は1回にまとめる。
            if (now - SpotLocalCache.lastNotifiedAt(context, spot.id) < NOTIFY_COOLDOWN_MS) {
                suppressed++
                return@forEach
            }
            SpotLocalCache.markNotified(context, spot.id, now)
            NotificationHelper.notifyNearby(context, spot)
            notified++
        }

        SpotLocalCache.saveLastGeofenceEvent(
            context,
            "ENTER 通知=${notified}件 抑制=${suppressed}件 不明=${unknown}件",
        )
    }

    companion object {
        const val ACTION_GEOFENCE_EVENT = "com.cloud42labo.serendipityspot.ACTION_GEOFENCE_EVENT"

        /** 同じスポットを再通知しない時間。 */
        private const val NOTIFY_COOLDOWN_MS = 3 * 60 * 60 * 1000L
    }
}
