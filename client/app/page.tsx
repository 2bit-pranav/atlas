import AppLayout from "@/components/layout/app-layout";
import TextInput from "@/components/text-input/text-input";

export default function Home() {
    return (
        <AppLayout>
            <div className="flex flex-1 flex-col justify-center">
                <div className="flex flex-1 items-center justify-center">
                    <h1
                        className="text-5xl font-semibold"
                        style={{
                            color: "var(--text)",
                        }}
                    >
                        Where do you want to start?
                    </h1>
                </div>

                <TextInput />
            </div>
        </AppLayout>
    );
}
