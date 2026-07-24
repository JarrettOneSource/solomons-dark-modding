#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"

#include <cmath>
#include <cstdint>
#include <iostream>

namespace {

bool Require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

bool NearlyEqual(float left, float right, float epsilon = 0.001f) {
    return std::fabs(left - right) <= epsilon;
}

sdmod::multiplayer::WorldSnapshotRuntimeInfo MakeWorldSnapshot(
    std::uint32_t sequence,
    std::uint64_t received_ms,
    float position_x) {
    using namespace sdmod::multiplayer;

    WorldActorSnapshot actor;
    actor.network_actor_id = 0x1001;
    actor.native_type_id = 1001;
    actor.position_x = position_x;
    actor.position_y = 20.0f;
    actor.heading = 350.0f;

    WorldSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id = 42;
    snapshot.received_ms = received_ms;
    snapshot.sequence = sequence;
    snapshot.scene_epoch = 7;
    snapshot.run_nonce = 11;
    snapshot.actor_total_count = 1;
    snapshot.scene_intent.kind = ParticipantSceneIntentKind::Run;
    snapshot.actors.push_back(actor);
    return snapshot;
}

bool AdaptiveWorldDelayKeepsABracketingSample() {
    using namespace sdmod::multiplayer;

    RuntimeState state;
    AppendWorldSnapshot(&state, MakeWorldSnapshot(1, 1000, 0.0f));
    AppendWorldSnapshot(&state, MakeWorldSnapshot(2, 1200, 20.0f));

    const auto delay_ms = RecommendedWorldSnapshotInterpolationDelayMs(state);
    WorldSnapshotRuntimeInfo sample;
    if (!Require(delay_ms == 300, "200 ms arrivals did not select a 300 ms delay") ||
        !Require(
            TrySampleWorldSnapshot(state, 1390, delay_ms, &sample),
            "adaptive world sample was unavailable") ||
        !Require(sample.actors.size() == 1, "adaptive world sample lost its actor") ||
        !Require(
            NearlyEqual(sample.actors[0].position_x, 9.0f),
            "adaptive world sample held the newest position instead of interpolating")) {
        return false;
    }

    AppendWorldSnapshot(&state, MakeWorldSnapshot(3, 1300, 30.0f));
    return Require(
        RecommendedWorldSnapshotInterpolationDelayMs(state) == 300,
        "recent p90 delay became too shallow after one faster arrival");
}

bool RemotePlayerExtrapolatesAtMostOneArrival() {
    using namespace sdmod::multiplayer;

    ParticipantInfo participant;
    participant.runtime.movement_intent_x = 1.0f;
    participant.runtime.movement_intent_y = 0.0f;

    ParticipantTransformSample first;
    first.valid = true;
    first.received_ms = 1000;
    first.sequence = 1;
    first.run_nonce = 11;
    first.scene_intent.kind = ParticipantSceneIntentKind::Run;
    first.position_x = 0.0f;

    auto second = first;
    second.received_ms = 1050;
    second.sequence = 2;
    second.position_x = 5.0f;
    AppendParticipantTransformSample(&participant, first);
    AppendParticipantTransformSample(&participant, second);

    ParticipantTransformSample sample;
    if (!Require(
            TrySampleParticipantTransform(participant, 1190, 120, &sample),
            "remote extrapolation sample was unavailable") ||
        !Require(
            NearlyEqual(sample.position_x, 7.0f),
            "remote extrapolation did not project the observed velocity")) {
        return false;
    }

    if (!Require(
            TrySampleParticipantTransform(participant, 1300, 120, &sample),
            "bounded remote extrapolation sample was unavailable") ||
        !Require(
            NearlyEqual(sample.position_x, 10.0f),
            "remote extrapolation exceeded or missed the one-arrival cap")) {
        return false;
    }

    participant.runtime.movement_intent_x = 0.0f;
    return Require(
               TrySampleParticipantTransform(participant, 1190, 120, &sample),
               "remote hold sample was unavailable") &&
           Require(
               NearlyEqual(sample.position_x, 5.0f),
               "remote extrapolation ignored the stopped movement intent");
}

bool PacketSplitsHaveBoundedVariableWireSizes() {
    using namespace sdmod::multiplayer;

    return Require(
               kProtocolVersion == 82,
               "native and launcher protocol version changed unexpectedly") &&
        Require(
            sizeof(StatePacket) == 604,
            "StatePacket regained checkpoint-array payload") &&
        Require(
            sizeof(ParticipantFramePacket) == 322,
            "ParticipantFramePacket regained wave-summary payload") &&
        Require(
            ParticipantInventorySnapshotPacketWireSize(0) ==
                kParticipantInventorySnapshotPacketPrefixBytes,
            "empty inventory snapshot wire size is invalid") &&
        Require(
            ParticipantProgressionBookSnapshotPacketWireSize(0) ==
                kParticipantProgressionBookSnapshotPacketPrefixBytes,
            "empty progression snapshot wire size is invalid") &&
        Require(
            LevelUpBarrierPacketWireSize(1) ==
                kLevelUpBarrierPacketPrefixBytes +
                    sizeof(LevelUpBarrierParticipantPacketState),
            "single-participant level-up barrier wire size is invalid") &&
        Require(
            IsValidLevelUpBarrierPacketWireSize(
                sizeof(LevelUpBarrierPacket),
                static_cast<std::uint8_t>(
                    kLevelUpWaitStatusMaxParticipants)),
            "250-participant level-up barrier does not consume its full packet") &&
        Require(
            !IsValidLevelUpBarrierPacketWireSize(
                sizeof(LevelUpBarrierPacket) - 1,
                static_cast<std::uint8_t>(
                    kLevelUpWaitStatusMaxParticipants)),
            "truncated level-up barrier wire size was accepted");
}

}  // namespace

int main() {
    if (!AdaptiveWorldDelayKeepsABracketingSample() ||
        !RemotePlayerExtrapolatesAtMostOneArrival() ||
        !PacketSplitsHaveBoundedVariableWireSizes()) {
        return 1;
    }

    std::cout << "Multiplayer runtime state tests passed\n";
    return 0;
}
