package com.cloud42labo.serendipityspot.data

import org.json.JSONArray
import org.json.JSONObject

/**
 * スプレッドシートの1行 = 1スポット。
 * rowIndex はシート上の行番号（ヘッダーを除く、1始まり）。ローカルキャッシュ由来の場合は -1。
 */
data class Spot(
    val id: String,
    val lat: Double,
    val lng: Double,
    val title: String,
    val memo: String,
    val radiusMeters: Float = 150f,
    val rowIndex: Int = -1,
)

fun List<Spot>.toJson(): String {
    val arr = JSONArray()
    forEach { spot ->
        arr.put(
            JSONObject().apply {
                put("id", spot.id)
                put("lat", spot.lat)
                put("lng", spot.lng)
                put("title", spot.title)
                put("memo", spot.memo)
                put("radiusMeters", spot.radiusMeters)
                put("rowIndex", spot.rowIndex)
            }
        )
    }
    return arr.toString()
}

fun String.toSpotList(): List<Spot> {
    if (isBlank()) return emptyList()
    val arr = JSONArray(this)
    return (0 until arr.length()).map { i ->
        val o = arr.getJSONObject(i)
        Spot(
            id = o.getString("id"),
            lat = o.getDouble("lat"),
            lng = o.getDouble("lng"),
            title = o.getString("title"),
            memo = o.optString("memo", ""),
            radiusMeters = o.optDouble("radiusMeters", 150.0).toFloat(),
            rowIndex = o.optInt("rowIndex", -1),
        )
    }
}
