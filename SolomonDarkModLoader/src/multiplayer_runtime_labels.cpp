#include "multiplayer_runtime_state.h"

#include <cmath>

namespace sdmod::multiplayer {

bool IsLocalHumanParticipant(const ParticipantInfo& participant) {
    return participant.kind == ParticipantKind::LocalHuman;
}

bool IsRemoteParticipant(const ParticipantInfo& participant) {
    return participant.kind == ParticipantKind::RemoteParticipant;
}

bool IsLuaControlledParticipant(const ParticipantInfo& participant) {
    return IsRemoteParticipant(participant) &&
           participant.controller_kind == ParticipantControllerKind::LuaBrain;
}

bool IsNativeControlledParticipant(const ParticipantInfo& participant) {
    return participant.controller_kind == ParticipantControllerKind::Native;
}

const char* SessionStatusLabel(SessionStatus status) {
    switch (status) {
    case SessionStatus::Idle:
        return "Idle";
    case SessionStatus::WaitingForInvite:
        return "WaitingForInvite";
    case SessionStatus::CreatingLobby:
        return "CreatingLobby";
    case SessionStatus::JoiningLobby:
        return "JoiningLobby";
    case SessionStatus::Handshaking:
        return "Handshaking";
    case SessionStatus::Ready:
        return "Ready";
    case SessionStatus::Error:
        return "Error";
    }
    return "Unknown";
}

const char* SessionTransportLabel(SessionTransportKind kind) {
    switch (kind) {
    case SessionTransportKind::None:
        return "None";
    case SessionTransportKind::Steam:
        return "Steam";
    case SessionTransportKind::LocalUdp:
        return "LocalUdp";
    }
    return "Unknown";
}

const char* ParticipantKindLabel(ParticipantKind kind) {
    switch (kind) {
    case ParticipantKind::LocalHuman:
        return "LocalHuman";
    case ParticipantKind::RemoteParticipant:
        return "RemoteParticipant";
    }
    return "Unknown";
}

const char* ParticipantControllerKindLabel(ParticipantControllerKind kind) {
    switch (kind) {
    case ParticipantControllerKind::Native:
        return "Native";
    case ParticipantControllerKind::LuaBrain:
        return "LuaBrain";
    }
    return "Unknown";
}

const char* ParticipantSceneIntentKindLabel(ParticipantSceneIntentKind kind) {
    switch (kind) {
    case ParticipantSceneIntentKind::SharedHub:
        return "SharedHub";
    case ParticipantSceneIntentKind::PrivateRegion:
        return "PrivateRegion";
    case ParticipantSceneIntentKind::Run:
        return "Run";
    }
    return "Unknown";
}

const char* LootDropKindLabel(LootDropKind kind) {
    switch (kind) {
    case LootDropKind::Unknown:
        return "Unknown";
    case LootDropKind::Gold:
        return "Gold";
    case LootDropKind::Item:
        return "Item";
    case LootDropKind::Potion:
        return "Potion";
    case LootDropKind::Orb:
        return "Orb";
    case LootDropKind::Powerup:
        return "Powerup";
    }
    return "Unknown";
}

float StockLootBehaviorDistance(LootDropKind kind, float pickup_range) {
    if (!std::isfinite(pickup_range) || pickup_range <= 0.0f) {
        return 0.0f;
    }

    float world_units_per_range = 0.0f;
    switch (kind) {
    case LootDropKind::Gold:
    case LootDropKind::Item:
    case LootDropKind::Potion:
        world_units_per_range = 30.0f;
        break;
    case LootDropKind::Orb:
        // Stock orbs begin pulling at 60x and collect once their moving actor
        // reaches 20x. Replicated presentation has no independent authority to
        // animate that pull, so the request boundary models its initiation.
        world_units_per_range = 60.0f;
        break;
    case LootDropKind::Powerup:
        world_units_per_range = 20.0f;
        break;
    case LootDropKind::Unknown:
    default:
        return 0.0f;
    }
    return pickup_range * world_units_per_range;
}

const char* LootPickupResultCodeLabel(LootPickupResultCode code) {
    switch (code) {
    case LootPickupResultCode::Accepted:
        return "Accepted";
    case LootPickupResultCode::Rejected:
        return "Rejected";
    case LootPickupResultCode::AlreadyGone:
        return "AlreadyGone";
    case LootPickupResultCode::OutOfRange:
        return "OutOfRange";
    case LootPickupResultCode::WrongRun:
        return "WrongRun";
    case LootPickupResultCode::Unsupported:
        return "Unsupported";
    }
    return "Unknown";
}

}  // namespace sdmod::multiplayer
