namespace {

struct CollisionGeometryPublicationCache {
    uintptr_t world_address = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t static_revision = 0;
    std::uint32_t dynamic_revision = 0;
    std::uint64_t static_hash = 0;
    std::uint64_t dynamic_hash = 0;
    bool static_hash_valid = false;
    bool dynamic_hash_valid = false;
    std::uint64_t next_geometry_id = 1;
    std::unordered_map<uintptr_t, std::uint64_t> circle_ids;
    std::unordered_map<uintptr_t, std::uint64_t> segment_ids;
    std::unordered_map<uintptr_t, std::uint64_t> polygon_ids;
};

std::mutex g_collision_geometry_publication_mutex;
CollisionGeometryPublicationCache
    g_collision_geometry_publication_cache;

void HashCollisionGeometryBytes(
    const void* bytes,
    std::size_t byte_count,
    std::uint64_t* hash) {
    if (bytes == nullptr || hash == nullptr) {
        return;
    }
    constexpr std::uint64_t kFnvPrime = 1099511628211ull;
    const auto* data =
        static_cast<const std::uint8_t*>(bytes);
    for (std::size_t index = 0; index < byte_count; ++index) {
        *hash ^= data[index];
        *hash *= kFnvPrime;
    }
}

template <typename Value>
void HashCollisionGeometryValue(
    const Value& value,
    std::uint64_t* hash) {
    HashCollisionGeometryBytes(
        &value,
        sizeof(value),
        hash);
}

std::uint64_t AllocateCollisionGeometryId(
    uintptr_t source_address,
    std::unordered_map<uintptr_t, std::uint64_t>* ids,
    CollisionGeometryPublicationCache* cache) {
    if (source_address == 0 || ids == nullptr || cache == nullptr) {
        return 0;
    }
    const auto existing = ids->find(source_address);
    if (existing != ids->end()) {
        return existing->second;
    }
    if (cache->next_geometry_id == 0 ||
        cache->next_geometry_id >
            static_cast<std::uint64_t>(INT64_MAX)) {
        return 0;
    }
    const auto id = cache->next_geometry_id++;
    ids->emplace(source_address, id);
    return id;
}

void ResetCollisionGeometryCacheForWorld(
    uintptr_t world_address,
    CollisionGeometryPublicationCache* cache) {
    if (cache == nullptr ||
        cache->world_address == world_address) {
        return;
    }
    cache->world_address = world_address;
    cache->scene_epoch += 1;
    if (cache->scene_epoch == 0) {
        cache->scene_epoch = 1;
    }
    cache->static_revision = 0;
    cache->dynamic_revision = 0;
    cache->static_hash = 0;
    cache->dynamic_hash = 0;
    cache->static_hash_valid = false;
    cache->dynamic_hash_valid = false;
    cache->next_geometry_id = 1;
    cache->circle_ids.clear();
    cache->segment_ids.clear();
    cache->polygon_ids.clear();
}

void HashCollisionCircle(
    const SDModCollisionCircle& circle,
    std::uint64_t* hash) {
    HashCollisionGeometryValue(circle.geometry_id, hash);
    HashCollisionGeometryValue(circle.native_type_id, hash);
    HashCollisionGeometryValue(circle.x, hash);
    HashCollisionGeometryValue(circle.y, hash);
    HashCollisionGeometryValue(circle.radius, hash);
    HashCollisionGeometryValue(circle.mask, hash);
    HashCollisionGeometryValue(circle.path_blocks, hash);
    HashCollisionGeometryValue(circle.pushable, hash);
    HashCollisionGeometryValue(circle.destructible, hash);
    HashCollisionGeometryValue(
        circle.destructible_resolved,
        hash);
}

void HashCollisionSegment(
    const SDModCollisionSegment& segment,
    std::uint64_t* hash) {
    HashCollisionGeometryValue(segment.geometry_id, hash);
    HashCollisionGeometryValue(segment.native_type_id, hash);
    HashCollisionGeometryValue(segment.start_x, hash);
    HashCollisionGeometryValue(segment.start_y, hash);
    HashCollisionGeometryValue(segment.end_x, hash);
    HashCollisionGeometryValue(segment.end_y, hash);
    HashCollisionGeometryValue(segment.mask, hash);
    HashCollisionGeometryValue(segment.path_blocks, hash);
    HashCollisionGeometryValue(segment.openable, hash);
}

void HashCollisionPolygon(
    const SDModCollisionPolygon& polygon,
    std::uint64_t* hash) {
    HashCollisionGeometryValue(polygon.geometry_id, hash);
    HashCollisionGeometryValue(polygon.native_type_id, hash);
    HashCollisionGeometryValue(polygon.bounds_x, hash);
    HashCollisionGeometryValue(polygon.bounds_y, hash);
    HashCollisionGeometryValue(polygon.bounds_w, hash);
    HashCollisionGeometryValue(polygon.bounds_h, hash);
    HashCollisionGeometryValue(polygon.path_blocks, hash);
    HashCollisionGeometryValue(polygon.points.size(), hash);
    for (const auto& point : polygon.points) {
        HashCollisionGeometryValue(point.x, hash);
        HashCollisionGeometryValue(point.y, hash);
    }
}

std::uint32_t ResolveCollisionGeometryRunNonce(
    const multiplayer::RuntimeState& runtime,
    std::uint64_t participant_id) {
    const auto* participant =
        multiplayer::FindParticipant(runtime, participant_id);
    return participant == nullptr
        ? 0
        : participant->runtime.run_nonce;
}

}  // namespace

bool TryGetGameplayCollisionGeometryState(
    std::uint64_t participant_id,
    SDModCollisionGeometryState* state,
    std::string* error_message) {
    if (state != nullptr) {
        *state = SDModCollisionGeometryState{};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };
    if (state == nullptr || participant_id == 0) {
        return fail(
            "Collision geometry requires an output and participant id.");
    }

    SDModParticipantGameplayState observer;
    if (!TryRefreshParticipantGameplayState(
            participant_id,
            &observer) ||
        !observer.available ||
        !observer.entity_materialized ||
        observer.actor_address == 0 ||
        observer.world_address == 0) {
        return fail(
            "Collision geometry requires a materialized participant.");
    }

    float observer_radius = 0.0f;
    std::uint32_t observer_collision_mask = 0;
    auto& memory = ProcessMemory::Instance();
    if (!TryReadFiniteFloatField(
            observer.actor_address,
            kActorCollisionRadiusOffset,
            &observer_radius) ||
        observer_radius <= 0.0f ||
        !memory.TryReadField(
            observer.actor_address,
            kActorPrimaryFlagMaskOffset,
            &observer_collision_mask) ||
        observer_collision_mask == 0) {
        return fail(
            "Collision geometry could not resolve the observer radius and mask.");
    }

    GameplayPathGridSnapshot snapshot;
    if (!TryBuildGameplayPathGridSnapshot(
            observer.world_address,
            &snapshot,
            error_message)) {
        return false;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    std::lock_guard<std::mutex> lock(
        g_collision_geometry_publication_mutex);
    auto& cache =
        g_collision_geometry_publication_cache;
    ResetCollisionGeometryCacheForWorld(
        observer.world_address,
        &cache);

    SDModCollisionGeometryState built;
    built.valid = true;
    built.scene_epoch = cache.scene_epoch;
    built.run_nonce =
        ResolveCollisionGeometryRunNonce(
            runtime,
            participant_id);
    built.refresh_pending = false;
    built.observer_radius = observer_radius;
    built.observer_radius_resolved = true;
    built.participant_collision_padding = 0.5f;

    built.circles.reserve(
        snapshot.circle_obstacles.size());
    for (const auto& source : snapshot.circle_obstacles) {
        // Wizard bodies are represented semantically below and must not
        // reintroduce the observing actor into its own collision truth.
        if (source.native_type_id == 1) {
            continue;
        }
        SDModCollisionCircle circle;
        circle.geometry_id = AllocateCollisionGeometryId(
            source.source_address,
            &cache.circle_ids,
            &cache);
        if (circle.geometry_id == 0) {
            continue;
        }
        circle.native_type_id = source.native_type_id;
        circle.x = source.x;
        circle.y = source.y;
        circle.radius = source.radius;
        circle.mask = source.mask;
        circle.pushable =
            (source.mask &
             GameplayPathPushableCircleObstacleMask()) != 0;
        circle.path_blocks =
            !circle.pushable &&
            (((source.mask &
               GameplayPathStaticCircleObstacleMask()) != 0) ||
             ((source.mask & observer_collision_mask) != 0));
        circle.destructible =
            source.native_type_id == 2061;
        circle.destructible_resolved =
            source.native_type_id == 2061 ||
            source.native_type_id == 3006;
        circle.dynamic = circle.destructible;
        built.circles.push_back(circle);
    }

    built.segments.reserve(
        snapshot.segment_obstacles.size());
    for (const auto& source : snapshot.segment_obstacles) {
        const auto source_key =
            source.object_address != 0
                ? source.object_address
                : source.record_address;
        SDModCollisionSegment segment;
        segment.geometry_id = AllocateCollisionGeometryId(
            source_key,
            &cache.segment_ids,
            &cache);
        if (segment.geometry_id == 0) {
            continue;
        }
        segment.native_type_id = source.native_type_id;
        segment.start_x = source.start_x;
        segment.start_y = source.start_y;
        segment.end_x = source.end_x;
        segment.end_y = source.end_y;
        segment.mask = source.mask;
        segment.openable = source.openable;
        segment.path_blocks = !segment.openable;
        segment.destructible = false;
        segment.destructible_resolved =
            source.native_type_id == 3007 ||
            source.native_type_id == 3011 ||
            source.native_type_id == 3012;
        segment.dynamic = source.dynamic;
        built.segments.push_back(segment);
    }

    built.polygons.reserve(
        snapshot.polygon_obstacles.size());
    for (const auto& source : snapshot.polygon_obstacles) {
        SDModCollisionPolygon polygon;
        polygon.geometry_id = AllocateCollisionGeometryId(
            source.source_address,
            &cache.polygon_ids,
            &cache);
        if (polygon.geometry_id == 0) {
            continue;
        }
        polygon.bounds_x = source.bounds_x;
        polygon.bounds_y = source.bounds_y;
        polygon.bounds_w = source.bounds_w;
        polygon.bounds_h = source.bounds_h;
        polygon.path_blocks = true;
        polygon.points = source.points;
        built.polygons.push_back(std::move(polygon));
    }

    built.participant_radii.reserve(
        runtime.participants.size());
    for (const auto& participant : runtime.participants) {
        if (participant.participant_id == 0) {
            continue;
        }
        SDModParticipantGameplayState gameplay;
        SDModCollisionParticipantRadius radius;
        radius.participant_id =
            participant.participant_id;
        if (TryGetParticipantGameplayState(
                participant.participant_id,
                &gameplay) &&
            gameplay.available &&
            gameplay.entity_materialized &&
            gameplay.actor_address != 0 &&
            gameplay.world_address ==
                observer.world_address &&
            TryReadFiniteFloatField(
                gameplay.actor_address,
                kActorCollisionRadiusOffset,
                &radius.radius) &&
            radius.radius > 0.0f) {
            radius.radius_resolved = true;
        }
        built.participant_radii.push_back(radius);
    }
    std::sort(
        built.participant_radii.begin(),
        built.participant_radii.end(),
        [](const auto& left, const auto& right) {
            return left.participant_id <
                right.participant_id;
        });

    constexpr std::uint64_t kFnvOffset =
        1469598103934665603ull;
    std::uint64_t static_hash = kFnvOffset;
    std::uint64_t dynamic_hash = kFnvOffset;
    for (const auto& circle : built.circles) {
        HashCollisionCircle(
            circle,
            circle.dynamic
                ? &dynamic_hash
                : &static_hash);
    }
    for (const auto& segment : built.segments) {
        HashCollisionSegment(
            segment,
            segment.dynamic
                ? &dynamic_hash
                : &static_hash);
    }
    for (const auto& polygon : built.polygons) {
        HashCollisionPolygon(
            polygon,
            polygon.dynamic
                ? &dynamic_hash
                : &static_hash);
    }
    for (const auto& radius : built.participant_radii) {
        HashCollisionGeometryValue(
            radius.participant_id,
            &dynamic_hash);
        HashCollisionGeometryValue(
            radius.radius,
            &dynamic_hash);
        HashCollisionGeometryValue(
            radius.radius_resolved,
            &dynamic_hash);
    }

    if (!cache.static_hash_valid ||
        cache.static_hash != static_hash) {
        cache.static_hash = static_hash;
        cache.static_hash_valid = true;
        cache.static_revision += 1;
        if (cache.static_revision == 0) {
            cache.static_revision = 1;
        }
    }
    if (!cache.dynamic_hash_valid ||
        cache.dynamic_hash != dynamic_hash) {
        cache.dynamic_hash = dynamic_hash;
        cache.dynamic_hash_valid = true;
        cache.dynamic_revision += 1;
        if (cache.dynamic_revision == 0) {
            cache.dynamic_revision = 1;
        }
    }
    built.static_revision = cache.static_revision;
    built.dynamic_revision = cache.dynamic_revision;
    *state = std::move(built);
    return true;
}
