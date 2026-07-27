#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

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

bool FixedWorldDelayDoesNotAmplifyArrivalJitter() {
    using namespace sdmod::multiplayer;

    RuntimeState state;
    AppendWorldSnapshot(&state, MakeWorldSnapshot(1, 1000, 0.0f));
    AppendWorldSnapshot(&state, MakeWorldSnapshot(2, 1200, 20.0f));

    WorldSnapshotRuntimeInfo sample;
    if (!Require(
            TrySampleWorldSnapshot(state, 1250, 150, &sample),
            "fixed-delay world sample was unavailable") ||
        !Require(
            sample.actors.size() == 1,
            "fixed-delay world sample lost its actor") ||
        !Require(
            NearlyEqual(sample.actors[0].position_x, 10.0f),
            "fixed-delay world sample did not interpolate at 150 ms")) {
        return false;
    }

    AppendWorldSnapshot(&state, MakeWorldSnapshot(3, 1300, 30.0f));
    return Require(
        TrySampleWorldSnapshot(state, 1350, 150, &sample) &&
            sample.actors.size() == 1 &&
            NearlyEqual(sample.actors[0].position_x, 20.0f),
        "arrival jitter changed the fixed 150 ms presentation delay");
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
               kProtocolVersion == 86,
               "native and launcher protocol version changed unexpectedly") &&
        Require(
            std::string(
                LobbySessionStateLabel(
                    LobbySessionState::NotInGame)) ==
                "not-in-game" &&
                std::string(
                    LobbySessionStateLabel(
                        LobbySessionState::InHub)) ==
                    "in-hub" &&
                std::string(
                    LobbySessionStateLabel(
                        LobbySessionState::InBoneyard)) ==
                    "in-boneyard",
            "lobby session-state JSON labels changed") &&
        Require(
            std::string(
                RunLoadingReleaseReasonLabel(
                    RunLoadingReleaseReason::
                        AllParticipantsReady)) ==
                "all-participants-ready" &&
                std::string(
                    RunLoadingReleaseReasonLabel(
                        RunLoadingReleaseReason::Timeout)) ==
                    "timeout",
            "run-loading release labels changed") &&
        Require(
            ResolveParticipantDeathPresentationTick(0) == 0 &&
                ResolveParticipantDeathPresentationTick(2500) == 150 &&
                ResolveParticipantDeathPresentationTick(2517) == 151 &&
                ResolveParticipantDeathPresentationTick(5000) == 298 &&
                ResolveParticipantDeathPresentationTick(10000) == 298,
            "death presentation wire clock is not bounded to the native lifecycle") &&
        Require(
            ResolveParticipantDeathPresentationStorageTick(149) == 149 &&
                ResolveParticipantDeathPresentationStorageTick(150) == 150 &&
                ResolveParticipantDeathPresentationStorageTick(151) == 150 &&
                ResolveParticipantDeathPresentationStorageTick(298) == 150,
            "death presentation CPU timer can cross the native side-effect boundary") &&
        Require(
            ResolveParticipantDeathPresentationRenderTick(149) == 149 &&
                ResolveParticipantDeathPresentationRenderTick(150) == 150 &&
                ResolveParticipantDeathPresentationRenderTick(151) == 151 &&
                ResolveParticipantDeathPresentationRenderTick(159) == 159 &&
                ResolveParticipantDeathPresentationRenderTick(298) == 159,
            "death presentation render projection does not reach and hold the corpse frame") &&
        Require(
            sizeof(StatePacket) == 653,
            "StatePacket regained checkpoint-array payload") &&
        Require(
            sizeof(ParticipantFramePacket) == 370,
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
    if (!FixedWorldDelayDoesNotAmplifyArrivalJitter() ||
        !RemotePlayerExtrapolatesAtMostOneArrival() ||
        !PacketSplitsHaveBoundedVariableWireSizes()) {
        return 1;
    }

    std::cout << "Multiplayer runtime state tests passed\n";
    return 0;
}
