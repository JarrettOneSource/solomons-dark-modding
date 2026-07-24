#include "multiplayer_runtime_protocol.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <iostream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace sdmod::multiplayer {
namespace {

void Log(const std::string&) {
}

#include "../../SolomonDarkModLoader/src/multiplayer_local_transport/world_snapshot_fragmentation.inl"
#include "../../SolomonDarkModLoader/src/multiplayer_local_transport/world_motion_snapshot_fragmentation.inl"

bool Require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

CompleteWorldSnapshotPacketState MakeSnapshot(
    std::uint32_t snapshot_id,
    float position_base) {
    CompleteWorldSnapshotPacketState snapshot;
    snapshot.authority_participant_id = 42;
    snapshot.scene_epoch = 7;
    snapshot.run_nonce = 11;
    snapshot.snapshot_id = snapshot_id;
    snapshot.scene_kind = WorldSceneKind::Run;
    for (std::uint64_t index = 0; index < 12; ++index) {
        WorldActorSnapshotPacketState actor{};
        actor.network_actor_id = 1000 + index;
        actor.native_type_id = 100 + static_cast<std::uint32_t>(index);
        actor.position_x = position_base + static_cast<float>(index);
        actor.position_y = 20.0f;
        actor.radius = 8.0f;
        actor.hp = 100.0f;
        actor.max_hp = 100.0f;
        snapshot.actors.push_back(actor);
    }
    return snapshot;
}

std::vector<WorldMotionSnapshotPacket> BuildMotionPackets(
    const CompleteWorldSnapshotPacketState& snapshot) {
    auto motion = BuildWorldMotionSnapshot(snapshot);
    std::uint32_t next_packet_sequence = 1;
    std::vector<WorldMotionSnapshotPacket> packets;
    if (!BuildWorldMotionSnapshotFragmentPackets(
            motion,
            &next_packet_sequence,
            &packets)) {
        return {};
    }
    return packets;
}

bool MissingFragmentsDoNotWithholdOtherEnemies() {
    const auto identity = MakeSnapshot(10, 0.0f);
    const auto generation_11 =
        BuildMotionPackets(MakeSnapshot(11, 100.0f));
    const auto generation_12 =
        BuildMotionPackets(MakeSnapshot(12, 200.0f));
    if (!Require(
            generation_11.size() == 2 &&
                generation_12.size() == 2,
            "test snapshot did not span two motion fragments")) {
        return false;
    }

    WorldMotionSnapshotMergeState merge_state;
    CompleteWorldSnapshotPacketState merged;
    if (!Require(
            TryApplyWorldMotionSnapshotFragment(
                generation_11[0],
                identity,
                &merge_state,
                &merged),
            "first partial generation was withheld") ||
        !Require(
            merged.actors[0].position_x == 100.0f,
            "first fragment did not update its first enemy") ||
        !Require(
            merged.actors[9].position_x == 109.0f,
            "first fragment did not update its last enemy") ||
        !Require(
            merged.actors[10].position_x == 10.0f,
            "missing fragment corrupted an untouched enemy")) {
        return false;
    }

    if (!Require(
            TryApplyWorldMotionSnapshotFragment(
                generation_12[1],
                identity,
                &merge_state,
                &merged),
            "later fragment could not independently update enemies") ||
        !Require(
            merged.actors[0].position_x == 100.0f,
            "later fragment regressed an enemy from another fragment") ||
        !Require(
            merged.actors[10].position_x == 210.0f,
            "later fragment did not update its first enemy") ||
        !Require(
            merged.actors[11].position_x == 211.0f,
            "later fragment did not update its last enemy")) {
        return false;
    }

    return Require(
               !TryApplyWorldMotionSnapshotFragment(
                   generation_11[1],
                   identity,
                   &merge_state,
                   &merged),
               "out-of-order fragment was accepted") &&
        Require(
            merge_state.snapshot.actors[10].position_x == 210.0f,
            "out-of-order fragment regressed enemy motion");
}

bool NewIdentityRefreshesUntouchedEnemies() {
    const auto old_identity = MakeSnapshot(20, 0.0f);
    const auto generation_21 =
        BuildMotionPackets(MakeSnapshot(21, 100.0f));
    const auto new_identity = MakeSnapshot(22, 200.0f);
    const auto generation_23 =
        BuildMotionPackets(MakeSnapshot(23, 300.0f));

    WorldMotionSnapshotMergeState merge_state;
    CompleteWorldSnapshotPacketState merged;
    if (!Require(
            TryApplyWorldMotionSnapshotFragment(
                generation_21[0],
                old_identity,
                &merge_state,
                &merged),
            "old identity motion setup failed") ||
        !Require(
            TryApplyWorldMotionSnapshotFragment(
                generation_23[0],
                new_identity,
                &merge_state,
                &merged),
            "new identity motion fragment failed")) {
        return false;
    }

    return Require(
               merged.actors[0].position_x == 300.0f,
               "new generation did not update its fragment") &&
        Require(
            merged.actors[11].position_x == 211.0f,
            "new identity did not refresh an untouched fragment");
}

}  // namespace
}  // namespace sdmod::multiplayer

int main() {
    using namespace sdmod::multiplayer;
    if (!MissingFragmentsDoNotWithholdOtherEnemies() ||
        !NewIdentityRefreshesUntouchedEnemies()) {
        return 1;
    }
    std::cout << "World motion fragment merge tests passed\n";
    return 0;
}
