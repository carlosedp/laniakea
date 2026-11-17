// Pre-analysis: import ESP32 ROM/peripheral symbols and seed functions at Xtensa ENTRY instructions.
// Arg 0: path to <elf>.symbols.txt  (lines: "name 0xADDR f|l")
//@category Laniakea
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.SourceType;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import java.nio.file.*;
import java.util.*;

public class ImportSymbols extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        int n = 0;
        if (args.length > 0) {
            for (String line : Files.readAllLines(Paths.get(args[0]))) {
                String[] p = line.trim().split("\\s+");
                if (p.length < 3) continue;
                Address a = toAddr(Long.decode(p[1]));
                if (currentProgram.getMemory().getBlock(a) == null) continue;
                try {
                    createLabel(a, p[0], true, SourceType.IMPORTED);
                    if (p[2].equals("f")) createFunction(a, p[0]);
                    n++;
                } catch (Exception e) { /* duplicate names etc. */ }
            }
        }
        println("imported " + n + " symbols");

        // Windowed-ABI functions start with ENTRY (byte0 = 0x36, low nibble of byte1 = 1 for a1)
        int seeded = 0;
        Memory mem = currentProgram.getMemory();
        for (MemoryBlock b : mem.getBlocks()) {
            if (!b.isInitialized() || !b.isExecute()) continue;
            byte[] data = new byte[(int) b.getSize()];
            b.getBytes(b.getStart(), data);
            for (int i = 0; i + 3 <= data.length; i += 4) {
                if ((data[i] & 0xff) == 0x36 && (data[i + 1] & 0x0f) == 0x01) {
                    Address a = b.getStart().add(i);
                    if (getFunctionAt(a) == null) {
                        new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
                        if (createFunction(a, null) != null) seeded++;
                    }
                }
            }
        }
        println("seeded " + seeded + " functions at ENTRY instructions");
    }
}
