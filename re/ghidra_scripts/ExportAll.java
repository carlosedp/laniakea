// Post-analysis export: decompiled C for every function, function list, and string -> function xrefs.
// Arg 0: output directory
//@category Laniakea
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.util.DefinedStringIterator;
import java.io.*;
import java.util.*;

public class ExportAll extends GhidraScript {
    @Override
    public void run() throws Exception {
        File out = new File(getScriptArgs()[0]);
        out.mkdirs();
        Listing listing = currentProgram.getListing();
        ReferenceManager rm = currentProgram.getReferenceManager();
        FunctionManager fm = currentProgram.getFunctionManager();

        // ---- strings -> referencing functions (direct, or via an L32R literal-pool slot)
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(out, "string_xrefs.txt")))) {
            for (Data d : DefinedStringIterator.forProgram(currentProgram)) {
                String s = StringDataInstance.getStringDataInstance(d).getStringValue();
                if (s == null || s.length() < 3) continue;
                Set<String> fns = new TreeSet<>();
                for (Reference r : rm.getReferencesTo(d.getAddress())) {
                    Function f = fm.getFunctionContaining(r.getFromAddress());
                    if (f != null) { fns.add(f.getName() + "@" + f.getEntryPoint()); continue; }
                    for (Reference r2 : rm.getReferencesTo(r.getFromAddress())) {   // literal pool slot
                        Function f2 = fm.getFunctionContaining(r2.getFromAddress());
                        if (f2 != null) fns.add(f2.getName() + "@" + f2.getEntryPoint());
                    }
                }
                w.printf("%s\t%s\t%s%n", d.getAddress(), s.replace("\n", "\\n").replace("\t", "\\t"), String.join(",", fns));
            }
        }

        // ---- functions list + decompilation
        DecompInterface di = new DecompInterface();
        DecompileOptions opt = new DecompileOptions();
        di.setOptions(opt);
        di.openProgram(currentProgram);
        int count = 0;
        try (PrintWriter fl = new PrintWriter(new FileWriter(new File(out, "functions.txt")));
             PrintWriter dc = new PrintWriter(new FileWriter(new File(out, "decompiled.c")))) {
            for (Function f : fm.getFunctions(true)) {
                if (monitor.isCancelled()) break;
                Address ep = f.getEntryPoint();
                if (ep.getOffset() >= 0x40000000L && ep.getOffset() < 0x40070000L) continue; // ROM
                int callers = f.getCallingFunctions(monitor).size();
                int callees = f.getCalledFunctions(monitor).size();
                fl.printf("%s\t%s\t%d\tcallers=%d\tcallees=%d%n", ep, f.getName(), f.getBody().getNumAddresses(), callers, callees);
                DecompileResults res = di.decompileFunction(f, 60, monitor);
                dc.printf("%n// ==== %s @ %s  (size %d)%n", f.getName(), ep, f.getBody().getNumAddresses());
                if (res != null && res.decompileCompleted()) dc.println(res.getDecompiledFunction().getC());
                else dc.println("// decompilation failed: " + (res == null ? "null" : res.getErrorMessage()));
                count++;
            }
        }
        di.dispose();
        println("exported " + count + " functions to " + out);
    }
}
