# Trace object-relative offsets derived from a global singleton pointer at the
# instruction level. This complements decompiler-source scans: the decompiler
# can discard ECX setup for untyped thiscall targets even though the machine
# code passes a sprite descriptor through ECX.
#
# Usage:
#   -postScript trace_singleton_register_offsets.py 0x008199E4 20
#
# The optional second argument is the maximum number of instructions followed
# after each singleton load (default 20, maximum 100).
# @category: Analysis

from ghidra.program.model.address import Address
from ghidra.program.model.lang import Register
from ghidra.program.model.scalar import Scalar


def parse_args():
    raw = []
    for argument in getScriptArgs():
        raw.extend(value.strip() for value in argument.split(";") if value.strip())
    if not raw:
        print("ERROR: expected <singleton-address> [instruction-limit]")
        raise SystemExit(1)
    limit = int(raw[1]) if len(raw) > 1 else 20
    if limit < 1 or limit > 100:
        print("ERROR: instruction limit must be in the range 1..100")
        raise SystemExit(1)
    return toAddr(raw[0]), limit


def operand_objects(instruction, index, object_type):
    return [
        value
        for value in instruction.getOpObjects(index)
        if isinstance(value, object_type)
    ]


def operand_text(instruction, index):
    return instruction.getDefaultOperandRepresentation(index).upper()


def direct_register_operand(instruction, index):
    if index >= instruction.getNumOperands():
        return None
    if "[" in operand_text(instruction, index):
        return None
    registers = operand_objects(instruction, index, Register)
    return registers[0] if len(registers) == 1 else None


def scalar_value(scalar):
    value = scalar.getSignedValue()
    # Ghidra sometimes models a positive x86 displacement as an unsigned
    # scalar. Preserve its ordinary positive form in that case.
    if value < 0 and scalar.getUnsignedValue() <= 0x7fffffff:
        return scalar.getUnsignedValue()
    return value


singleton, instruction_limit = parse_args()
listing = currentProgram.getListing()
function_manager = currentProgram.getFunctionManager()

loads = []
for reference in getReferencesTo(singleton):
    instruction = listing.getInstructionContaining(reference.getFromAddress())
    if instruction is None or instruction.getMnemonicString().upper() != "MOV":
        continue
    destination = direct_register_operand(instruction, 0)
    if destination is None:
        continue
    source_addresses = operand_objects(instruction, 1, Address)
    if singleton not in source_addresses:
        continue
    function = function_manager.getFunctionContaining(instruction.getAddress())
    if function is not None:
        loads.append((function, instruction, destination))

loads.sort(key=lambda entry: str(entry[1].getAddress()))

print("=== SINGLETON REGISTER OFFSETS ===")
print("SINGLETON %s" % singleton)
print("INSTRUCTION_LIMIT %d" % instruction_limit)
print("LOAD_COUNT %d" % len(loads))

seen = set()
for function, load, destination in loads:
    aliases = {destination.getName(): 0}
    cursor = load
    for distance in range(1, instruction_limit + 1):
        cursor = cursor.getNext()
        if cursor is None or not function.getBody().contains(cursor.getAddress()):
            break

        mnemonic = cursor.getMnemonicString().upper()
        destination_register = direct_register_operand(cursor, 0)
        destination_name = (
            destination_register.getName() if destination_register is not None else None
        )
        derived_destination = None

        # Record memory operands before mutating aliases. An access can be a
        # sprite field read such as [ECX + 0x94] after ECX already points at a
        # particular descriptor.
        for operand_index in range(cursor.getNumOperands()):
            if "[" not in operand_text(cursor, operand_index):
                continue
            registers = operand_objects(cursor, operand_index, Register)
            tracked = [register for register in registers if register.getName() in aliases]
            if len(tracked) != 1:
                continue
            scalars = operand_objects(cursor, operand_index, Scalar)
            displacement = scalar_value(scalars[-1]) if scalars else 0
            effective = aliases[tracked[0].getName()] + displacement
            key = (str(load.getAddress()), str(cursor.getAddress()), "MEMORY", effective)
            if key not in seen:
                seen.add(key)
                print(
                    "USE function=%s address=%s load=%s access=%s distance=%d "
                    "kind=MEMORY register=%s offset=%s instruction=%s"
                    % (
                        function.getName(),
                        function.getEntryPoint(),
                        load.getAddress(),
                        cursor.getAddress(),
                        distance,
                        tracked[0].getName(),
                        hex(effective),
                        cursor,
                    )
                )

        # Preserve or derive aliases through the common x86 pointer-building
        # forms emitted by this executable.
        if mnemonic == "MOV" and destination_name is not None:
            source_register = direct_register_operand(cursor, 1)
            if source_register is not None and source_register.getName() in aliases:
                derived_destination = aliases[source_register.getName()]
        elif mnemonic in ("ADD", "SUB") and destination_name in aliases:
            scalars = operand_objects(cursor, 1, Scalar)
            if scalars:
                delta = scalar_value(scalars[-1])
                if mnemonic == "SUB":
                    delta = -delta
                derived_destination = aliases[destination_name] + delta
                key = (str(load.getAddress()), str(cursor.getAddress()), "POINTER", derived_destination)
                if key not in seen:
                    seen.add(key)
                    print(
                        "USE function=%s address=%s load=%s access=%s distance=%d "
                        "kind=POINTER register=%s offset=%s instruction=%s"
                        % (
                            function.getName(),
                            function.getEntryPoint(),
                            load.getAddress(),
                            cursor.getAddress(),
                            distance,
                            destination_name,
                            hex(derived_destination),
                            cursor,
                        )
                    )
        elif mnemonic == "LEA" and destination_name is not None:
            source_registers = operand_objects(cursor, 1, Register)
            tracked = [
                register for register in source_registers
                if register.getName() in aliases
            ]
            if len(tracked) == 1:
                scalars = operand_objects(cursor, 1, Scalar)
                displacement = scalar_value(scalars[-1]) if scalars else 0
                derived_destination = aliases[tracked[0].getName()] + displacement
                key = (str(load.getAddress()), str(cursor.getAddress()), "POINTER", derived_destination)
                if key not in seen:
                    seen.add(key)
                    print(
                        "USE function=%s address=%s load=%s access=%s distance=%d "
                        "kind=POINTER register=%s offset=%s instruction=%s"
                        % (
                            function.getName(),
                            function.getEntryPoint(),
                            load.getAddress(),
                            cursor.getAddress(),
                            distance,
                            destination_name,
                            hex(derived_destination),
                            cursor,
                        )
                    )

        if destination_name is not None:
            if derived_destination is None:
                aliases.pop(destination_name, None)
            else:
                aliases[destination_name] = derived_destination

        # A call consumes thiscall ECX and invalidates the volatile registers.
        # The pointer-building instruction immediately before it has already
        # been reported.
        if mnemonic == "CALL":
            aliases.pop("EAX", None)
            aliases.pop("ECX", None)
            aliases.pop("EDX", None)
        if mnemonic in ("RET", "JMP") or not aliases:
            break

print("=== DONE ===")
